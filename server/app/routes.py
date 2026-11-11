import os
import redis
from rq import Queue
from rq.job import Job
from rq.exceptions import NoSuchJobError
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError, DataError

from app import db
from app.models import Admin, Subject
from app.auth import (
    ACCESS_TOKEN_EXPIRES,
    create_jwt_token,
    decode_jwt_token,
    extract_bearer_token,
    verify_password,
)
from app.repositories.student_repository import StudentRepository
from app.repositories.subject_repository import SubjectRepository
from app.repositories.sync_repository import SyncRepository
from app.tasks import process_csv_import

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
        payload = decode_jwt_token(token)
    except ValueError as exc:
        return error_response("INVALID_TOKEN", str(exc), 401)

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
        payload = decode_jwt_token(token)
    except ValueError as exc:
        return error_response("INVALID_TOKEN", str(exc), 401)

    admin_id = payload.get("sub")
    admin = Admin.query.filter_by(admin_id=admin_id, deleted_at=None).first()
    if not admin:
        return error_response("ADMIN_NOT_FOUND", "Không tìm thấy tài khoản quản trị viên.", 404)

    return jsonify({"admin": admin.to_dict(include_password=False)}), 200


@api_bp.route("/students", methods=["GET"])
def list_students():
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    students = StudentRepository.get_all(limit=max(1, min(limit, 500)), offset=max(0, offset))
    return jsonify({"count": len(students), "students": [s.to_dict() for s in students]}), 200


@api_bp.route("/subjects", methods=["GET"])
def list_subjects():
    instructor_id = request.args.get("instructor_id")
    if instructor_id:
        subjects = SubjectRepository.get_by_instructor(instructor_id)
    else:
        subjects = Subject.query.filter_by(deleted_at=None).all()
    return jsonify({"count": len(subjects), "subjects": [s.to_dict() for s in subjects]}), 200


@api_bp.route("/admins", methods=["GET"])
def list_admins():
    admins = Admin.query.filter_by(deleted_at=None).all()
    return jsonify({"count": len(admins), "admins": [a.to_dict(include_password=False) for a in admins]}), 200


@api_bp.route("/import/csv", methods=["POST"])
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


