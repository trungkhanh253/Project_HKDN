import os
import redis
from rq import Queue
from rq.job import Job
from rq.exceptions import NoSuchJobError
from sqlalchemy.exc import IntegrityError, DataError
from flask import Blueprint, jsonify, request, g
from app.models import Admin, Subject, Student
from app.permissions import filter_accessible
from app.services.password_reset_service import create_password_reset_token
from app.services.email_service import send_password_reset_email
from app.services.password_reset_service import reset_password
from flask import current_app
from redis.exceptions import RedisError
from app.services.token_revocation_service import (
    revoke_token,
    is_token_revoked,
)

from app import db
from app.models import Admin, Subject, Student, Enrollment, CheckinHistory
from app.auth import (
    ACCESS_TOKEN_EXPIRES,
    create_jwt_token,
    decode_jwt_token,
    extract_bearer_token,
    verify_password,
    require_auth,
)
from app.repositories.student_repository import StudentRepository
from app.repositories.subject_repository import SubjectRepository
from app.repositories.sync_repository import SyncRepository
from app.repositories.checkin_repository import CheckinRepository
from app.repositories.admin_repository import AdminRepository
from app.tasks import process_csv_import
from app.permissions import PermissionDenied
import re
import uuid

from app.auth import hash_password_sha256

api_bp = Blueprint("api_v1", __name__)


def error_response(code: str, message: str, status_code: int = 400, details: dict = None):
    body = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status_code


def _get_redis_conn():
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    return redis.from_url(redis_url)


@api_bp.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy"}), 200

@api_bp.route("/auth/register", methods=["POST"])
@require_auth
def auth_register():
    # Chỉ SUPER_ADMIN được đăng ký tài khoản
    if g.current_admin.role != "SUPER_ADMIN":
        return error_response(
            "FORBIDDEN",
            "Chỉ SUPER_ADMIN mới được tạo tài khoản.",
            403,
        )

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return error_response(
            "INVALID_JSON",
            "Body phải là JSON hợp lệ.",
            400,
        )

    fields = (
        "email",
        "password",
        "confirm_password",
        "full_name",
        "admin_code",
    )

    for field in fields:
        if not isinstance(data.get(field), str) or not data[field].strip():
            return error_response(
                "VALIDATION_ERROR",
                f"Trường '{field}' không được để trống.",
                422,
            )

    email = data["email"].strip().lower()
    password = data["password"]
    confirm_password = data["confirm_password"]
    full_name = data["full_name"].strip()
    admin_code = data["admin_code"].strip()

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return error_response(
            "INVALID_EMAIL",
            "Email không hợp lệ.",
            422,
        )

    if len(password) < 6:
        return error_response(
            "INVALID_PASSWORD",
            "Mật khẩu phải có ít nhất 6 ký tự.",
            422,
        )

    if password != confirm_password:
        return error_response(
            "PASSWORD_MISMATCH",
            "Mật khẩu xác nhận không khớp.",
            422,
        )

    if Admin.query.filter_by(email=email).first():
        return error_response(
            "EMAIL_EXISTS",
            "Email đã tồn tại.",
            409,
        )

    if Admin.query.filter_by(admin_code=admin_code).first():
        return error_response(
            "ADMIN_CODE_EXISTS",
            "Mã giảng viên đã tồn tại.",
            409,
        )

    admin = Admin(
        admin_id="ADM_" + uuid.uuid4().hex[:12].upper(),
        uuid=str(uuid.uuid4()),
        email=email,
        password=hash_password_sha256(password),
        full_name=full_name,
        admin_code=admin_code,
        date_of_birth=data.get("date_of_birth"),
        phone=data.get("phone"),
        gender=data.get("gender"),
        role="ADMIN",
    )

    try:
        db.session.add(admin)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error_response(
            "REGISTER_CONFLICT",
            "Email hoặc mã giảng viên đã tồn tại.",
            409,
        )

    return jsonify({
        "message": "Đăng ký tài khoản thành công.",
        "admin": {
            "admin_id": admin.admin_id,
            "email": admin.email,
            "full_name": admin.full_name,
            "admin_code": admin.admin_code,
            "role": admin.role,
        },
    }), 201

@api_bp.route("/auth/change-password", methods=["POST"])
@require_auth
def auth_change_password():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return error_response(
            "INVALID_JSON",
            "Body phải là JSON hợp lệ.",
            400,
        )

    old_password = data.get("old_password")
    new_password = data.get("new_password")
    confirm_password = data.get("confirm_password")

    if not all(
        isinstance(value, str) and value
        for value in (
            old_password,
            new_password,
            confirm_password,
        )
    ):
        return error_response(
            "VALIDATION_ERROR",
            "Vui lòng nhập đầy đủ mật khẩu cũ, mật khẩu mới và xác nhận mật khẩu.",
            422,
        )

    if not verify_password(old_password, g.current_admin.password):
        return error_response(
            "INVALID_OLD_PASSWORD",
            "Mật khẩu cũ không chính xác.",
            400,
        )

    if len(new_password) < 6:
        return error_response(
            "INVALID_PASSWORD",
            "Mật khẩu mới phải có ít nhất 6 ký tự.",
            422,
        )

    if new_password != confirm_password:
        return error_response(
            "PASSWORD_MISMATCH",
            "Mật khẩu xác nhận không khớp.",
            422,
        )

    if verify_password(new_password, g.current_admin.password):
        return error_response(
            "SAME_PASSWORD",
            "Mật khẩu mới phải khác mật khẩu cũ.",
            422,
        )

    g.current_admin.password = hash_password_sha256(new_password)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return error_response(
            "UPDATE_FAILED",
            "Không thể cập nhật mật khẩu.",
            500,
        )

    return jsonify({
        "message": "Đổi mật khẩu thành công. Vui lòng đăng nhập lại."
    }), 200

@api_bp.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(
            "INVALID_JSON",
            "Body request phải là JSON hợp lệ chứa email (hoặc username) và password.",
            400,
        )

    identifier = (data.get("email") or data.get("username") or data.get("admin_id") or "").strip()
    password = data.get("password") or ""

    if not identifier or not password:
        return error_response(
            "VALIDATION_ERROR",
            "Vui lòng cung cấp đầy đủ email (hoặc username) và password.",
            422,
        )

    admin = (
        Admin.query.filter(
            (Admin.email == identifier)
            | (Admin.admin_id == identifier)
            | (Admin.admin_code == identifier),
            Admin.deleted_at.is_(None),
        ).first()
    )

    if not admin or not verify_password(password, admin.password):
        return error_response(
            "INVALID_CREDENTIALS",
            "Email hoặc mật khẩu không chính xác.",
            401,
        )

    access_token = create_jwt_token(
        admin_id=admin.admin_id,
        email=admin.email,
        role=admin.role,
        token_type="access",
    )
    refresh_token = create_jwt_token(
        admin_id=admin.admin_id,
        email=admin.email,
        role=admin.role,
        token_type="refresh",
    )

    return (
        jsonify(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "Bearer",
                "expires_in": ACCESS_TOKEN_EXPIRES,
                "admin": {
                    "admin_id": admin.admin_id,
                    "uuid": admin.uuid,
                    "email": admin.email,
                    "full_name": admin.full_name,
                    "role": admin.role,
                    "is_first_login": admin.is_first_login,
                },
            }
        ),
        200,
    )


@api_bp.route("/auth/logout", methods=["POST"])
def auth_logout():
    access_token = extract_bearer_token()

    if not access_token:
        return error_response(
            "MISSING_TOKEN",
            "Thiếu Access Token trong Authorization header.",
            401,
        )

    data = request.get_json(silent=True)
    refresh_token = data.get("refresh_token") if isinstance(data, dict) else None

    if not isinstance(refresh_token, str) or not refresh_token.strip():
        return error_response(
            "MISSING_REFRESH_TOKEN",
            "Vui lòng cung cấp Refresh Token.",
            400,
        )

    try:
        access_payload = decode_jwt_token(
            access_token,
            expected_type="access",
        )

        refresh_payload = decode_jwt_token(
            refresh_token,
            expected_type="refresh",
        )

        if access_payload["sub"] != refresh_payload["sub"]:
            return error_response(
                "TOKEN_MISMATCH",
                "Access Token và Refresh Token không thuộc cùng tài khoản.",
                401,
            )

        # Thu hồi cả Access Token và Refresh Token
        revoke_token(access_token, access_payload)
        revoke_token(refresh_token, refresh_payload)

    except ValueError:
        return error_response(
            "INVALID_TOKEN",
            "Token không hợp lệ, đã hết hạn hoặc đã bị thu hồi.",
            401,
        )

    except RedisError:
        return error_response(
            "AUTH_SERVICE_UNAVAILABLE",
            "Không thể xác nhận trạng thái phiên đăng nhập. Vui lòng thử lại.",
            503,
        )

    return jsonify({
        "message": "Đăng xuất thành công."
    }), 200


@api_bp.route("/auth/refresh", methods=["POST"])
def auth_refresh():
    token = extract_bearer_token()
    if not token:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            token = body.get("refresh_token")

    if not token:
        return error_response(
            "MISSING_TOKEN",
            "Thiếu token xác thực trong header Authorization (Bearer <token>).",
            401,
        )

    try:
        payload = decode_jwt_token(
            token,
            expected_type="refresh"
        )

    except ValueError as exc:
        return error_response(
            "INVALID_TOKEN",
            str(exc),
            401
        )

    except RedisError:
        return error_response(
            "AUTH_SERVICE_UNAVAILABLE",
            "Dịch vụ xác thực tạm thời không khả dụng.",
            503
        )

    new_access_token = create_jwt_token(
        admin_id=payload.get("sub", ""),
        email=payload.get("email", ""),
        role=payload.get("role", "ADMIN"),
        token_type="access",
    )

    return (
        jsonify(
            {
                "access_token": new_access_token,
                "token_type": "Bearer",
                "expires_in": ACCESS_TOKEN_EXPIRES,
            }
        ),
        200,
    )


@api_bp.route("/auth/me", methods=["GET"])
def auth_me():
    token = extract_bearer_token()
    if not token:
        return error_response(
            "MISSING_TOKEN",
            "Thiếu token xác thực trong header Authorization (Bearer <token>).",
            401,
        )
    try:
        payload = decode_jwt_token(
            token,
            expected_type="access"
        )

    except ValueError as exc:
        return error_response(
            "INVALID_TOKEN",
            str(exc),
            401
        )

    except RedisError:
        return error_response(
            "AUTH_SERVICE_UNAVAILABLE",
            "Dịch vụ xác thực tạm thời không khả dụng.",
            503
        )

    admin_id = payload.get("sub")
    admin = Admin.query.filter_by(admin_id=admin_id, deleted_at=None).first()
    if not admin:
        return error_response("ADMIN_NOT_FOUND", "Không tìm thấy tài khoản quản trị viên.", 404)

    return jsonify({"admin": admin.to_dict(include_password=False)}), 200


def _get_authenticated_admin():
    token = extract_bearer_token()
    if not token:
        return None, error_response(
            "MISSING_TOKEN",
            "Thiếu token xác thực trong header Authorization (Bearer <token>).",
            401,
        )
    try:
        payload = decode_jwt_token(token, expected_type="access")
    except ValueError as exc:
        return None, error_response("INVALID_TOKEN", str(exc), 401)

    admin_id = payload.get("sub")
    admin = Admin.query.filter_by(admin_id=admin_id, deleted_at=None).first()
    if not admin:
        return None, error_response("ADMIN_NOT_FOUND", "Không tìm thấy tài khoản quản trị viên.", 404)

    return admin, None


# ==========================================
# GĐ 8 & GĐ 3: API SINH VIÊN (CRUD & Phân quyền)
# ==========================================

@api_bp.route("/students", methods=["GET"])
@require_auth
def list_students():
    limit = max(1, min(request.args.get("limit", 100, type=int), 500))
    offset = max(0, request.args.get("offset", 0, type=int))
    q = request.args.get("q")
    sort = request.args.get("sort")

    query = Student.query.filter(Student.deleted_at.is_(None))
    query = filter_accessible(query, Student)

    if q:
        kw = f"%{q.strip()}%"
        query = query.filter(
            (Student.student_id.ilike(kw))
            | (Student.full_name.ilike(kw))
            | (Student.email.ilike(kw))
            | (Student.phone.ilike(kw))
        )

    if sort:
        parts = sort.split(":")
        col_name = parts[0]
        direction = parts[1].lower() if len(parts) > 1 else "asc"
        col = getattr(Student, col_name, None)
        if col is not None:
            query = query.order_by(col.desc() if direction == "desc" else col.asc())
        else:
            query = query.order_by(Student.student_id.asc())
    else:
        query = query.order_by(Student.student_id.asc())

    total = query.count()
    students = query.limit(limit).offset(offset).all()
    items_data = [s.to_public_dict() if hasattr(s, "to_public_dict") else s.to_dict() for s in students]

    return jsonify({
        "items": items_data,
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(items_data),
        "students": items_data,
    }), 200


@api_bp.route("/students/<string:student_id>", methods=["GET"])
def get_student_detail(student_id: str):
    student = StudentRepository.get_by_id(student_id)
    if not student:
        return error_response("STUDENT_NOT_FOUND", f"Không tìm thấy sinh viên với mã '{student_id}'.", 404)
    return jsonify({"student": student.to_dict()}), 200


@api_bp.route("/students", methods=["POST"])
def create_student():
    admin, err = _get_authenticated_admin()
    if err:
        return err

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("INVALID_JSON", "Body request phải là JSON object.", 400)

    student_id = (data.get("student_id") or "").strip()
    full_name = (data.get("full_name") or "").strip()
    subject_id = (data.get("subject_id") or "").strip() or None

    if not student_id or not full_name:
        return error_response("VALIDATION_ERROR", "Trường student_id và full_name là bắt buộc.", 422)

    # Phân quyền: nếu có subject_id và là giảng viên (ADMIN thường), kiểm tra môn có thuộc giảng viên này không
    if subject_id and admin.role != "SUPER_ADMIN":
        subj = Subject.query.filter_by(subject_id=subject_id, deleted_at=None).first()
        if not subj:
            return error_response("SUBJECT_NOT_FOUND", f"Không tìm thấy môn học '{subject_id}'.", 404)
        if subj.instructor_id != admin.admin_id:
            return error_response("FORBIDDEN", "Giảng viên chỉ có quyền thao tác trên môn học do mình phụ trách.", 403)

    try:
        student = StudentRepository.create_student(data, subject_id=subject_id)
        return jsonify({
            "status": "created",
            "message": "Tạo sinh viên thành công.",
            "student": student.to_dict()
        }), 201
    except ValueError as ve:
        return error_response("STUDENT_CONFLICT", str(ve), 409)


@api_bp.route("/students/<string:student_id>", methods=["PUT"])
def update_student(student_id: str):
    admin, err = _get_authenticated_admin()
    if err:
        return err

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("INVALID_JSON", "Body request phải là JSON object.", 400)

    student = StudentRepository.get_by_id(student_id)
    if not student:
        return error_response("STUDENT_NOT_FOUND", f"Không tìm thấy sinh viên với mã '{student_id}'.", 404)

    # Phân quyền: nếu là giảng viên, kiểm tra sinh viên có thuộc ít nhất một môn của giảng viên này không
    if admin.role != "SUPER_ADMIN":
        enrolled_in_my_subjects = (
            db.session.query(Enrollment)
            .join(Subject, Enrollment.subject_id == Subject.subject_id)
            .filter(
                Enrollment.student_id == student_id,
                Enrollment.deleted_at.is_(None),
                Subject.instructor_id == admin.admin_id,
                Subject.deleted_at.is_(None),
            )
            .first()
        )
        if not enrolled_in_my_subjects:
            return error_response("FORBIDDEN", "Giảng viên chỉ được chỉnh sửa sinh viên thuộc lớp học phần mình phụ trách.", 403)

    updated = StudentRepository.update_student(student_id, data)
    return jsonify({
        "status": "updated",
        "message": "Cập nhật thông tin sinh viên thành công.",
        "student": updated.to_dict()
    }), 200


@api_bp.route("/students/<string:student_id>", methods=["DELETE"])
def delete_student(student_id: str):
    admin, err = _get_authenticated_admin()
    if err:
        return err

    student = StudentRepository.get_by_id(student_id)
    if not student:
        return error_response("STUDENT_NOT_FOUND", f"Không tìm thấy sinh viên với mã '{student_id}'.", 404)

    if admin.role != "SUPER_ADMIN":
        enrolled_in_my_subjects = (
            db.session.query(Enrollment)
            .join(Subject, Enrollment.subject_id == Subject.subject_id)
            .filter(
                Enrollment.student_id == student_id,
                Enrollment.deleted_at.is_(None),
                Subject.instructor_id == admin.admin_id,
                Subject.deleted_at.is_(None),
            )
            .first()
        )
        if not enrolled_in_my_subjects:
            return error_response("FORBIDDEN", "Giảng viên chỉ được xóa sinh viên thuộc lớp học phần mình phụ trách.", 403)

    StudentRepository.soft_delete_student(student_id)
    return jsonify({
        "status": "deleted",
        "message": f"Đã xóa mềm sinh viên '{student_id}'.",
        "student_id": student_id,
    }), 200


# ==========================================
# GĐ 3: API ĐIỂM DANH (POST & GET /attendance)
# ==========================================

@api_bp.route("/attendance", methods=["POST"])
def record_attendance():
    admin, err = _get_authenticated_admin()
    if err:
        return err

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("INVALID_JSON", "Body request phải là JSON object.", 400)

    student_id = (data.get("student_id") or "").strip()
    subject_id = (data.get("subject_id") or "").strip()
    checkin_time = (data.get("checkin_time") or "").strip()
    checkin_date = (data.get("checkin_date") or "").strip()
    uuid_str = (data.get("uuid") or "").strip() or None

    if not student_id or not subject_id or not checkin_time or not checkin_date:
        return error_response(
            "VALIDATION_ERROR",
            "Các trường student_id, subject_id, checkin_time và checkin_date là bắt buộc.",
            422,
        )

    student = Student.query.filter_by(student_id=student_id, deleted_at=None).first()
    if not student:
        return error_response("STUDENT_NOT_FOUND", f"Không tìm thấy sinh viên với mã '{student_id}'.", 404)

    subject = Subject.query.filter_by(subject_id=subject_id, deleted_at=None).first()
    if not subject:
        return error_response("SUBJECT_NOT_FOUND", f"Không tìm thấy môn học với mã '{subject_id}'.", 404)

    if admin.role != "SUPER_ADMIN" and subject.instructor_id != admin.admin_id:
        return error_response("FORBIDDEN", "Môn học này không thuộc quyền phụ trách của giảng viên.", 403)

    enr = Enrollment.query.filter_by(student_id=student_id, subject_id=subject_id, deleted_at=None).first()
    if not enr:
        return error_response(
            "STUDENT_NOT_ENROLLED",
            f"Sinh viên '{student_id}' chưa ghi danh vào môn học '{subject_id}'.",
            422,
        )

    checkin, is_created = CheckinRepository.record_checkin(
        student_id=student_id,
        subject_id=subject_id,
        checkin_time=checkin_time,
        checkin_date=checkin_date,
        uuid_str=uuid_str,
    )

    status_code = 201 if is_created else 200
    return jsonify({
        "status": "created" if is_created else "already_exists",
        "created": is_created,
        "message": "Ghi nhận điểm danh thành công." if is_created else "Bản ghi điểm danh với uuid này đã tồn tại.",
        "checkin": checkin.to_dict(),
    }), status_code


@api_bp.route("/attendance", methods=["GET"])
def list_attendance():
    subject_id = request.args.get("subject_id")
    checkin_date = request.args.get("date") or request.args.get("checkin_date")
    student_id = request.args.get("student_id")
    limit = max(1, min(request.args.get("limit", 100, type=int), 500))
    offset = max(0, request.args.get("offset", 0, type=int))

    items, total = CheckinRepository.get_history(
        subject_id=subject_id,
        checkin_date=checkin_date,
        student_id=student_id,
        limit=limit,
        offset=offset,
    )

    items_data = [c.to_dict() for c in items]
    return jsonify({
        "items": items_data,
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(items_data),
        "attendance": items_data,
    }), 200


# ==========================================
# GĐ 8: CHUẨN HÓA API SUBJECTS & ADMINS
# ==========================================

@api_bp.route("/subjects", methods=["GET"])
@require_auth
def list_subjects():
    limit = max(1, min(request.args.get("limit", 100, type=int), 500))
    offset = max(0, request.args.get("offset", 0, type=int))
    q = request.args.get("q")
    sort = request.args.get("sort")
    instructor_id = request.args.get("instructor_id")

    query = Subject.query.filter(Subject.deleted_at.is_(None))
    query = filter_accessible(query, Subject)

    if instructor_id:
        query = query.filter(Subject.instructor_id == instructor_id)

    if q:
        kw = f"%{q.strip()}%"
        query = query.filter(
            (Subject.subject_id.ilike(kw)) | (Subject.subject_name.ilike(kw))
        )

    if sort:
        parts = sort.split(":")
        col_name = parts[0]
        direction = parts[1].lower() if len(parts) > 1 else "asc"
        col = getattr(Subject, col_name, None)
        if col is not None:
            query = query.order_by(col.desc() if direction == "desc" else col.asc())
        else:
            query = query.order_by(Subject.subject_id.asc())
    else:
        query = query.order_by(Subject.subject_id.asc())

    total = query.count()
    subjects = query.limit(limit).offset(offset).all()
    items_data = [s.to_dict() for s in subjects]

    return jsonify({
        "items": items_data,
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(items_data),
        "subjects": items_data,
    }), 200


@api_bp.route("/subjects/<string:subject_id>", methods=["GET"])
def get_subject_detail(subject_id: str):
    subject = SubjectRepository.get_by_id(subject_id)
    if not subject:
        return error_response("SUBJECT_NOT_FOUND", f"Không tìm thấy môn học với mã '{subject_id}'.", 404)
    return jsonify({"subject": subject.to_dict()}), 200


@api_bp.route("/subjects", methods=["POST"])
@require_auth
def create_subject():
    admin, err = _get_authenticated_admin()
    if err:
        return err

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("INVALID_JSON", "Body request phải là JSON object.", 400)

    subject_id = (data.get("subject_id") or "").strip()
    subject_name = (data.get("subject_name") or "").strip()

    if not subject_id or not subject_name:
        return error_response("VALIDATION_ERROR", "Trường subject_id và subject_name là bắt buộc.", 422)

    # Phân quyền: nếu là giảng viên (ADMIN), tự động gán instructor_id là chính mình
    if admin.role != "SUPER_ADMIN":
        data["instructor_id"] = admin.admin_id
    else:
        if not data.get("instructor_id"):
            data["instructor_id"] = admin.admin_id

    data["created_by"] = admin.admin_id

    existing = SubjectRepository.get_by_id(subject_id, include_deleted=True)
    if existing:
        if existing.deleted_at is None:
            return error_response("SUBJECT_CONFLICT", f"Môn học với mã '{subject_id}' đã tồn tại.", 409)
        now = SubjectRepository.get_current_time()
        existing.deleted_at = None
        existing.subject_name = subject_name
        existing.time_slot = data.get("time_slot")
        existing.instructor_id = data.get("instructor_id")
        existing.subject_status = data.get("subject_status", "ASSIGNED")
        existing.semester_start_date = data.get("semester_start_date")
        existing.semester_end_date = data.get("semester_end_date")
        existing.updated_at = now
        db.session.commit()
        return jsonify(existing.to_dict()), 201

    try:
        new_subj = SubjectRepository.create(data)
        return jsonify(new_subj.to_dict()), 201
    except Exception as exc:
        db.session.rollback()
        return error_response("CREATE_SUBJECT_FAILED", f"Không thể tạo môn học: {str(exc)}", 400)


@api_bp.route("/subjects/<string:subject_id>", methods=["PUT"])
@require_auth
def update_subject(subject_id: str):
    admin, err = _get_authenticated_admin()
    if err:
        return err

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("INVALID_JSON", "Body request phải là JSON object.", 400)

    subject = SubjectRepository.get_by_id(subject_id)
    if not subject:
        return error_response("SUBJECT_NOT_FOUND", f"Không tìm thấy môn học với mã '{subject_id}'.", 404)

    # Phân quyền: Giảng viên chỉ được sửa môn của chính mình
    if admin.role != "SUPER_ADMIN" and subject.instructor_id != admin.admin_id:
        return error_response("FORBIDDEN", "Bạn không có quyền chỉnh sửa môn học này.", 403)

    if admin.role != "SUPER_ADMIN" and "instructor_id" in data:
        data["instructor_id"] = admin.admin_id

    updated = SubjectRepository.update(subject_id, data)
    return jsonify(updated.to_dict()), 200


@api_bp.route("/subjects/<string:subject_id>", methods=["DELETE"])
@require_auth
def delete_subject(subject_id: str):
    admin, err = _get_authenticated_admin()
    if err:
        return err

    subject = SubjectRepository.get_by_id(subject_id)
    if not subject:
        return error_response("SUBJECT_NOT_FOUND", f"Không tìm thấy môn học với mã '{subject_id}'.", 404)

    if admin.role != "SUPER_ADMIN" and subject.instructor_id != admin.admin_id:
        return error_response("FORBIDDEN", "Bạn không có quyền xóa môn học này.", 403)

    SubjectRepository.soft_delete(subject_id)
    return "", 204


@api_bp.route("/subjects/<string:subject_id>/students", methods=["GET"])
@require_auth
def get_subject_students(subject_id: str):
    admin, err = _get_authenticated_admin()
    if err:
        return err

    subject = SubjectRepository.get_by_id(subject_id)
    if not subject:
        return error_response("SUBJECT_NOT_FOUND", f"Không tìm thấy môn học với mã '{subject_id}'.", 404)

    if admin.role != "SUPER_ADMIN" and subject.instructor_id != admin.admin_id:
        return error_response("FORBIDDEN", "Bạn không có quyền xem danh sách sinh viên của môn học này.", 403)

    limit = max(1, min(request.args.get("limit", 50, type=int), 500))
    offset = max(0, request.args.get("offset", 0, type=int))
    q = request.args.get("q")

    items, total = SubjectRepository.get_enrolled_students(subject_id, limit=limit, offset=offset, q=q)
    return jsonify({
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }), 200


@api_bp.route("/subjects/<string:subject_id>/students", methods=["POST"])
@require_auth
def enroll_student_to_subject(subject_id: str):
    admin, err = _get_authenticated_admin()
    if err:
        return err

    subject = SubjectRepository.get_by_id(subject_id)
    if not subject:
        return error_response("SUBJECT_NOT_FOUND", f"Không tìm thấy môn học với mã '{subject_id}'.", 404)

    if admin.role != "SUPER_ADMIN" and subject.instructor_id != admin.admin_id:
        return error_response("FORBIDDEN", "Bạn không có quyền ghi danh sinh viên vào môn học này.", 403)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("INVALID_JSON", "Body request phải là JSON object.", 400)

    student_id = (data.get("student_id") or "").strip()
    if not student_id:
        return error_response("VALIDATION_ERROR", "Trường student_id là bắt buộc.", 422)

    enrollment_status = data.get("enrollment_status", "Enrolled")

    try:
        enr, already_exists = SubjectRepository.enroll_student(subject_id, student_id, enrollment_status)
        if already_exists:
            return error_response("ENROLLMENT_CONFLICT", f"Sinh viên '{student_id}' đã được ghi danh vào môn học này.", 409)
        return jsonify(enr.to_dict()), 201
    except KeyError as ke:
        return error_response("NOT_FOUND", str(ke), 404)
    except Exception as exc:
        db.session.rollback()
        return error_response("ENROLL_FAILED", f"Lỗi ghi danh: {str(exc)}", 400)


@api_bp.route("/subjects/<string:subject_id>/students/<string:student_id>", methods=["DELETE"])
@require_auth
def unenroll_student_from_subject(subject_id: str, student_id: str):
    admin, err = _get_authenticated_admin()
    if err:
        return err

    subject = SubjectRepository.get_by_id(subject_id)
    if not subject:
        return error_response("SUBJECT_NOT_FOUND", f"Không tìm thấy môn học với mã '{subject_id}'.", 404)

    if admin.role != "SUPER_ADMIN" and subject.instructor_id != admin.admin_id:
        return error_response("FORBIDDEN", "Bạn không có quyền hủy ghi danh sinh viên của môn học này.", 403)

    success = SubjectRepository.unenroll_student(subject_id, student_id)
    if not success:
        return error_response("ENROLLMENT_NOT_FOUND", f"Sinh viên '{student_id}' chưa ghi danh hoặc đã bị hủy khỏi môn học này.", 404)

    return "", 204


@api_bp.route("/admins", methods=["GET"])
@require_auth
def list_admins():
    limit = max(1, min(request.args.get("limit", 100, type=int), 500))
    offset = max(0, request.args.get("offset", 0, type=int))
    q = request.args.get("q")
    sort = request.args.get("sort")

    query = Admin.query.filter(Admin.deleted_at.is_(None))
    query = filter_accessible(query, Admin)

    if q:
        kw = f"%{q.strip()}%"
        query = query.filter(
            (Admin.admin_id.ilike(kw))
            | (Admin.full_name.ilike(kw))
            | (Admin.email.ilike(kw))
            | (Admin.phone.ilike(kw))
        )

    if sort:
        parts = sort.split(":")
        col_name = parts[0]
        direction = parts[1].lower() if len(parts) > 1 else "asc"
        col = getattr(Admin, col_name, None)
        if col is not None:
            query = query.order_by(col.desc() if direction == "desc" else col.asc())
        else:
            query = query.order_by(Admin.admin_id.asc())
    else:
        query = query.order_by(Admin.admin_id.asc())

    total = query.count()
    admins = query.limit(limit).offset(offset).all()
    items_data = [a.to_dict(include_password=False) for a in admins]

    return jsonify({
        "items": items_data,
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(items_data),
        "admins": items_data,
    }), 200


@api_bp.route("/admins/<string:admin_id>", methods=["GET"])
def get_admin_detail(admin_id: str):
    admin = AdminRepository.get_by_id(admin_id)
    if not admin:
        return error_response("ADMIN_NOT_FOUND", f"Không tìm thấy tài khoản quản trị viên '{admin_id}'.", 404)
    return jsonify({"admin": admin.to_dict(include_password=False)}), 200


@api_bp.route("/import/csv", methods=["POST"])
@require_auth
def import_csv():
    if "file" not in request.files:
        return error_response(
            "MISSING_FILE",
            "Thiếu tệp CSV tải lên (trường 'file' trong multipart/form-data là bắt buộc).",
            400,
        )

    uploaded_file = request.files["file"]
    if not uploaded_file or not uploaded_file.filename:
        return error_response(
            "EMPTY_FILENAME",
            "Tên tệp tải lên không hợp lệ hoặc trống.",
            400,
        )

    raw_bytes = uploaded_file.read()
    if not raw_bytes or not raw_bytes.strip():
        return error_response(
            "EMPTY_FILE",
            "Tệp CSV tải lên rỗng.",
            400,
        )

    try:
        csv_content = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_content = raw_bytes.decode("latin-1")

    import_type = request.form.get("type") or request.args.get("type")
    subject_id = request.form.get("subject_id") or request.args.get("subject_id")

    conn = _get_redis_conn()
    queue = Queue("default", connection=conn)
    job = queue.enqueue(
        process_csv_import,
        csv_content,
        import_type,
        subject_id,
        job_timeout=300,
        result_ttl=86400,
    )

    return (
        jsonify(
            {
                "job_id": job.id,
                "status": "queued",
                "message": "Đã nhận file CSV và đưa vào hàng đợi xử lý.",
            }
        ),
        202,
    )


@api_bp.route("/jobs/<string:job_id>", methods=["GET"])
@require_auth
def get_job_status(job_id: str):
    conn = _get_redis_conn()
    try:
        job = Job.fetch(job_id, connection=conn)
    except NoSuchJobError:
        return error_response(
            "JOB_NOT_FOUND",
            f"Không tìm thấy tác vụ nền với id '{job_id}'.",
            404,
        )
    except Exception as exc:
        return error_response(
            "JOB_FETCH_ERROR",
            f"Không thể truy vấn trạng thái job: {str(exc)}",
            404,
        )

    raw_status = job.get_status(refresh=True)
    status_str = raw_status.value if hasattr(raw_status, "value") else str(raw_status)

    return (
        jsonify(
            {
                "job_id": job.id,
                "status": status_str,
                "created_at": job.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if job.created_at else None,
                "ended_at": job.ended_at.strftime("%Y-%m-%dT%H:%M:%SZ") if job.ended_at else None,
                "result": job.result if status_str == "finished" else None,
                "error": job.exc_info if status_str == "failed" else None,
            }
        ),
        200,
    )


@api_bp.route("/sync/push", methods=["POST"])
@require_auth
def sync_push():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response(
            "INVALID_JSON",
            "Body request phải là một JSON object chứa dữ liệu đồng bộ.",
            400,
        )

    try:
        result = SyncRepository.push_changes(payload)
        return jsonify(result), 200
    except IntegrityError as exc:
        db.session.rollback()
        orig_msg = str(getattr(exc, "orig", exc))
        return error_response(
            "INTEGRITY_CONFLICT",
            "Vi phạm ràng buộc khóa ngoại (Foreign Key) hoặc tính duy nhất (Unique) khi đồng bộ.",
            409,
            details={"db_error": orig_msg},
        )
    except (ValueError, DataError) as exc:
        db.session.rollback()
        return error_response(
            "VALIDATION_ERROR",
            str(exc),
            422,
        )


@api_bp.route("/sync/pull", methods=["GET", "POST"])
@require_auth
def sync_pull():
    is_android_since_seq = "since_seq" in request.args
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if "since_seq" in body:
            is_android_since_seq = True
        raw_after_seq = body.get(
            "after_seq",
            body.get("since_seq", request.args.get("after_seq", request.args.get("since_seq", 0))),
        )
        raw_limit = body.get("limit", request.args.get("limit", 100))
    else:
        raw_after_seq = request.args.get("after_seq", request.args.get("since_seq", 0))
        raw_limit = request.args.get("limit", 100)

    try:
        after_seq = int(raw_after_seq)
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return error_response(
            "INVALID_PARAMS",
            "Tham số 'after_seq' (hoặc 'since_seq') và 'limit' phải là số nguyên.",
            400,
        )

    if after_seq < 0 or limit <= 0:
        return error_response(
            "INVALID_PARAMS",
            "Tham số 'after_seq' phải >= 0 và 'limit' phải > 0.",
            400,
        )

    flat_mode = is_android_since_seq or request.args.get("format") == "flat"
    result = SyncRepository.pull_all_changes(
        after_seq=after_seq,
        limit=limit,
        flat_changes=flat_mode,
    )
    return jsonify(result), 200


@api_bp.route("/sync/status", methods=["GET"])
@require_auth
def sync_status():
    return (
        jsonify(
            {
                "status": "ok",
                "latest_seq": SyncRepository.get_latest_seq(),
            }
        ),
        200,
    )


@api_bp.app_errorhandler(PermissionDenied)
def handle_permission_denied(error):
    db.session.rollback()
    return error_response(
        "FORBIDDEN",
        str(error),
        403
    )


@api_bp.route("/auth/forgot-password", methods=["POST"])
def auth_forgot_password():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return error_response(
            "INVALID_JSON",
            "Dữ liệu JSON không hợp lệ.",
            400
        )

    email = data.get("email")

    if not isinstance(email, str) or not email.strip():
        return error_response(
            "VALIDATION_ERROR",
            "Email không được để trống.",
            422
        )

    email = email.strip().lower()

    # Không tiết lộ email có tồn tại trong hệ thống hay không.
    success_response = {
        "message": (
            "Nếu email tồn tại trong hệ thống, "
            "hướng dẫn đặt lại mật khẩu sẽ được gửi."
        )
    }

    try:
        token = create_password_reset_token(email)

        if token is not None:
            send_password_reset_email(email, token)

    except Exception:
        # Không ghi token hoặc thông tin nhạy cảm vào log.
        current_app.logger.exception(
            "Password reset request failed"
        )

        return error_response(
            "RESET_REQUEST_FAILED",
            "Không thể xử lý yêu cầu lúc này.",
            503
        )

    return jsonify(success_response), 200


@api_bp.route("/auth/reset-password", methods=["POST"])
def auth_reset_password():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return error_response(
            "INVALID_JSON",
            "Dữ liệu JSON không hợp lệ.",
            400
        )

    email = data.get("email")
    token = data.get("token")
    new_password = data.get("new_password")
    confirm_password = data.get("confirm_password")

    if not all(
        isinstance(value, str) and value.strip()
        for value in [email, token, new_password, confirm_password]
    ):
        return error_response(
            "VALIDATION_ERROR",
            "Vui lòng nhập đầy đủ thông tin.",
            422
        )

    email = email.strip().lower()

    if len(new_password) < 6:
        return error_response(
            "INVALID_PASSWORD",
            "Mật khẩu mới phải có ít nhất 6 ký tự.",
            422
        )

    if new_password != confirm_password:
        return error_response(
            "PASSWORD_MISMATCH",
            "Mật khẩu xác nhận không khớp.",
            422
        )

    try:
        success = reset_password(email, token, new_password)

        if not success:
            return error_response(
                "INVALID_RESET_TOKEN",
                "Token không hợp lệ hoặc đã hết hạn.",
                400
            )

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Password reset failed")
        return error_response(
            "RESET_FAILED",
            "Không thể đặt lại mật khẩu lúc này.",
            500
        )

    return jsonify({
        "message": "Đặt lại mật khẩu thành công. Vui lòng đăng nhập lại."
    }), 200
