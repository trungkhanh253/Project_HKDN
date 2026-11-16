from datetime import date, datetime, time, timezone
from functools import wraps
from types import SimpleNamespace

from flask import Blueprint, g, jsonify, request
from sqlalchemy import String, Text, and_, func

from app import db
from app.auth import decode_jwt_token, extract_bearer_token
from app.models import CheckinHistory, Enrollment, Student, Subject

bp = Blueprint("checkins", __name__)

MAX_LIMIT = 500
SORT_FIELDS = {
    "checkin_date": CheckinHistory.checkin_date,
    "checkin_time": CheckinHistory.checkin_time,
    "updated_at": CheckinHistory.updated_at,
}

_DATE_COL_IS_TEXT = isinstance(CheckinHistory.__table__.c.checkin_date.type, (String, Text))



def api_error(status, code, message, details=None):
    """Cùng định dạng với error_response() trong routes.py: {"error": {"code", "message"}}."""
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def jwt_required():
    """Xác thực giống /auth/me: đọc Bearer token, giải mã access token, lưu admin vào g."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = extract_bearer_token()
            if not token:
                return api_error(401, "MISSING_TOKEN",
                                 "Thiếu token xác thực trong header Authorization (Bearer <token>).")
            try:
                payload = decode_jwt_token(token, expected_type="access")
            except ValueError as exc:
                return api_error(401, "INVALID_TOKEN", str(exc))
            admin_id = payload.get("sub") or payload.get("admin_id")
            if not admin_id:
                return api_error(401, "INVALID_TOKEN", "Token không chứa mã admin.")
            g.current_admin = SimpleNamespace(admin_id=admin_id, role=payload.get("role"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def current_admin():
    return g.current_admin



def _now():
    """Thời gian UTC, không có múi giờ: khớp db.DateTime + datetime.utcnow của SyncMetadataMixin."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fmt(value):
    """JSON: date-time ISO-8601 UTC, ngày YYYY-MM-DD, giờ HH:MM:SS."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _checkin_json(c, student_name):
    return {
        "checkin_id": c.checkin_id,
        "student_id": c.student_id,
        "subject_id": c.subject_id,
        "student_name": student_name,
        "checkin_time": _fmt(c.checkin_time),
        "checkin_date": _fmt(c.checkin_date),
        "uuid": str(c.uuid) if c.uuid is not None else None,
        "updated_at": _fmt(c.updated_at),
        "deleted_at": _fmt(c.deleted_at),
        "seq": c.seq,
    }


def _int_arg(name, default, lo, hi=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"Tham số '{name}' phải là số nguyên.")
    value = max(value, lo)
    return min(value, hi) if hi is not None else value


def _date_arg(name):
    """Đọc YYYY-MM-DD; trả về đúng kiểu của cột checkin_date (chuỗi ISO hoặc date)."""
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"Tham số '{name}' phải có dạng YYYY-MM-DD.")
    return parsed.isoformat() if _DATE_COL_IS_TEXT else parsed


def _date_range():
    d_from, d_to = _date_arg("date_from"), _date_arg("date_to")
    if d_from is not None and d_to is not None and d_from > d_to:
        raise ValueError("'date_from' không được lớn hơn 'date_to'.")
    return d_from, d_to


def _sort_arg():
    raw = request.args.get("sort") or "-checkin_date"
    descending = raw.startswith("-")
    name = raw.lstrip("-")
    if name not in SORT_FIELDS:
        raise ValueError("Tham số 'sort' hợp lệ: checkin_date, checkin_time, updated_at.")
    return name, descending


def _allowed_subject_ids(admin):
    """None = không giới hạn (SUPER_ADMIN). Ngược lại: tập mã môn mà giảng viên này phụ trách.
    Nếu nhóm đã có hàm dùng chung ở task 'Phân quyền', gọi hàm đó thay cho hàm này."""
    if admin.role == "SUPER_ADMIN":
        return None
    rows = (
        db.session.query(Subject.subject_id)
        .filter(Subject.instructor_id == admin.admin_id, Subject.deleted_at.is_(None))
        .all()
    )
    return {r[0] for r in rows}



@bp.get("/checkins")
@jwt_required()
def list_checkins():
    admin = current_admin()
    try:
        limit = _int_arg("limit", 50, 1, MAX_LIMIT)
        offset = _int_arg("offset", 0, 0)
        d_from, d_to = _date_range()
        sort_name, descending = _sort_arg()
    except ValueError as exc:
        return api_error(422, "VALIDATION_ERROR", str(exc))

    subject_id = request.args.get("subject_id") or None
    student_id = request.args.get("student_id") or None

    allowed = _allowed_subject_ids(admin)
    if allowed is not None and subject_id and subject_id not in allowed:
        return api_error(403, "FORBIDDEN", "Bạn không có quyền xem điểm danh của môn này.")

    query = (
        db.session.query(CheckinHistory, Student.full_name)
        .outerjoin(Student, Student.student_id == CheckinHistory.student_id)
        .filter(CheckinHistory.deleted_at.is_(None))
    )
    if allowed is not None:
        if not allowed:  # giảng viên chưa có môn nào
            return jsonify({"items": [], "total": 0, "limit": limit, "offset": offset})
        query = query.filter(CheckinHistory.subject_id.in_(allowed))
    if subject_id:
        query = query.filter(CheckinHistory.subject_id == subject_id)
    if student_id:
        query = query.filter(CheckinHistory.student_id == student_id)
    if d_from is not None:
        query = query.filter(CheckinHistory.checkin_date >= d_from)
    if d_to is not None:
        query = query.filter(CheckinHistory.checkin_date <= d_to)

    total = query.with_entities(func.count(CheckinHistory.checkin_id)).scalar() or 0

    direction = (lambda col: col.desc()) if descending else (lambda col: col.asc())
    order = [direction(SORT_FIELDS[sort_name])]
    if sort_name == "checkin_date":
        order.append(direction(CheckinHistory.checkin_time))
    order.append(direction(CheckinHistory.checkin_id))  # khóa phụ để phân trang ổn định

    rows = query.order_by(*order).limit(limit).offset(offset).all()
    return jsonify({
        "items": [_checkin_json(c, name) for c, name in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    })



@bp.delete("/checkins/<int:checkin_id>")
@jwt_required()
def delete_checkin(checkin_id):
    admin = current_admin()
    checkin = (
        db.session.query(CheckinHistory)
        .filter(CheckinHistory.checkin_id == checkin_id, CheckinHistory.deleted_at.is_(None))
        .first()
    )
    if checkin is None:
        return api_error(404, "NOT_FOUND", "Không tìm thấy lượt điểm danh.")

    allowed = _allowed_subject_ids(admin)
    if allowed is not None and checkin.subject_id not in allowed:
        return api_error(403, "FORBIDDEN", "Bạn không có quyền xóa điểm danh của môn này.")

    # Xóa mềm. Cập nhật cả updated_at: nếu không, app Android đẩy lại bản cũ (cùng updated_at)

    now = _now()
    checkin.deleted_at = now
    checkin.updated_at = now
    db.session.commit()
    return "", 204



@bp.get("/subjects/<subject_id>/attendance-summary")
@jwt_required()
def attendance_summary(subject_id):
    admin = current_admin()
    try:
        d_from, d_to = _date_range()
    except ValueError as exc:
        return api_error(422, "VALIDATION_ERROR", str(exc))

    subject = (
        db.session.query(Subject)
        .filter(Subject.subject_id == subject_id, Subject.deleted_at.is_(None))
        .first()
    )
    if subject is None:
        return api_error(404, "NOT_FOUND", "Không tìm thấy môn học.")
    allowed = _allowed_subject_ids(admin)
    if allowed is not None and subject_id not in allowed:
        return api_error(403, "FORBIDDEN", "Bạn không có quyền xem thống kê của môn này.")

    conditions = [CheckinHistory.subject_id == subject_id, CheckinHistory.deleted_at.is_(None)]
    if d_from is not None:
        conditions.append(CheckinHistory.checkin_date >= d_from)
    if d_to is not None:
        conditions.append(CheckinHistory.checkin_date <= d_to)
    in_scope = and_(*conditions)

    # Số buổi = số ngày khác nhau có ít nhất một lượt điểm danh của môn trong khoảng lọc.
    total_sessions = (
        db.session.query(func.count(func.distinct(CheckinHistory.checkin_date))).filter(in_scope).scalar() or 0
    )

    # Mỗi sinh viên đã ghi danh một dòng. Điều kiện ngày/môn đặt trong ON của outer join
    present = func.count(func.distinct(CheckinHistory.checkin_date))
    rows = (
        db.session.query(Student.student_id, Student.full_name, present)
        .join(Enrollment, Enrollment.student_id == Student.student_id)
        .outerjoin(CheckinHistory, and_(CheckinHistory.student_id == Student.student_id, in_scope))
        .filter(
            Enrollment.subject_id == subject_id,
            Enrollment.deleted_at.is_(None),
            Student.deleted_at.is_(None),
        )
        .group_by(Student.student_id, Student.full_name)
        .order_by(Student.student_id)
        .all()
    )

    items = []
    for sid, full_name, present_count in rows:
        present_count = int(present_count or 0)
        items.append({
            "student_id": sid,
            "full_name": full_name,
            "present_count": present_count,
            "absent_count": max(total_sessions - present_count, 0),
            "attendance_rate": round(present_count / total_sessions, 4) if total_sessions else 0.0,
        })
    return jsonify({"subject_id": subject_id, "total_sessions": total_sessions, "items": items})