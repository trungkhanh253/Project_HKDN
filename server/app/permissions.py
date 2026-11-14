from flask import g
from sqlalchemy import select

from app.models import (
    Admin,
    Subject,
    Student,
    Enrollment,
    CheckinHistory,
    EmailRecipient,
)
from app import db


class PermissionDenied(Exception):
    """Người dùng không có quyền truy cập tài nguyên."""
    pass


def current_admin():
    """Lấy tài khoản đã được xác thực bởi @require_auth."""
    admin = getattr(g, "current_admin", None)

    if admin is None:
        raise PermissionDenied("Chưa xác thực tài khoản.")

    return admin


def is_super_admin():
    """Kiểm tra tài khoản có phải SUPER_ADMIN không."""
    return current_admin().role == "SUPER_ADMIN"


def accessible_subject_ids():
    """
    Trả về truy vấn các subject_id mà ADMIN được truy cập.

    SUPER_ADMIN không bị giới hạn môn học.
    """
    admin = current_admin()

    query = select(Subject.subject_id).where(
        Subject.deleted_at.is_(None)
    )

    if admin.role == "SUPER_ADMIN":
        return query

    if admin.role == "ADMIN":
        return query.where(
            Subject.instructor_id == admin.admin_id
        )

    raise PermissionDenied("Role không được hỗ trợ.")


def filter_accessible(query, model):
    """
    Lọc SQLAlchemy Query theo quyền của tài khoản hiện tại.
    """
    admin = current_admin()

    if admin.role == "SUPER_ADMIN":
        return query

    if admin.role != "ADMIN":
        raise PermissionDenied("Role không được hỗ trợ.")

    subject_ids = accessible_subject_ids()

    if model is Subject:
        return query.filter(
            Subject.subject_id.in_(subject_ids)
        )

    if model in (Enrollment, CheckinHistory, EmailRecipient):
        return query.filter(
            model.subject_id.in_(subject_ids)
        )

    if model is Student:
        student_ids = select(Enrollment.student_id).where(
            Enrollment.subject_id.in_(subject_ids),
            Enrollment.deleted_at.is_(None)
        )

        return query.filter(
            Student.student_id.in_(student_ids)
        )

    if model is Admin:
        return query.filter(
            Admin.admin_id == admin.admin_id
        )

    raise ValueError(
        f"Chưa cấu hình phân quyền cho model: {model.__name__}"
    )


def can_access_subject(subject_id):
    """Kiểm tra quyền truy cập một môn học cụ thể."""
    admin = current_admin()

    if admin.role == "SUPER_ADMIN":
        return True

    if admin.role != "ADMIN":
        return False

    if not subject_id:
        return False

    return Subject.query.filter(
        Subject.subject_id == subject_id,
        Subject.instructor_id == admin.admin_id,
        Subject.deleted_at.is_(None)
    ).first() is not None


def require_subject_access(subject_id):
    """Từ chối truy cập khi môn học không thuộc giảng viên."""
    if not can_access_subject(subject_id):
        raise PermissionDenied(
            "Bạn không có quyền truy cập môn học này."
        )




def require_sync_batch_access(changes):
    """
    changes: [(table_name, item, existing), ...]

    Kiểm tra quyền toàn bộ lô trước khi ghi.
    Cho phép ADMIN tạo môn + sinh viên + enrollment
    trong cùng một lô.
    """
    admin = current_admin()

    if admin.role == "SUPER_ADMIN":
        return

    if admin.role != "ADMIN":
        raise PermissionDenied("Role không được hỗ trợ.")

    admin_id = admin.admin_id

    # Môn mới hợp lệ được tạo trong cùng lô.
    new_subject_ids = set()

    for table_name, item, existing in changes:
        if table_name != "subjects" or existing is not None:
            continue

        subject_id = item.get("subject_id")

        if not subject_id:
            raise PermissionDenied("Thiếu mã môn học.")

        if item.get("instructor_id") != admin_id:
            raise PermissionDenied(
                "ADMIN chỉ được tạo môn cho chính mình."
            )

        if item.get("created_by", admin_id) != admin_id:
            raise PermissionDenied(
                "Không được tạo môn thay tài khoản khác."
            )

        new_subject_ids.add(subject_id)

    def allowed_subject(subject_id):
        return (
            subject_id in new_subject_ids
            or can_access_subject(subject_id)
        )

    # Sinh viên được ghi danh vào môn hợp lệ trong lô.
    batch_student_ids = set()

    for table_name, item, existing in changes:
        if table_name != "enrollments":
            continue

        subject_id = (
            existing.subject_id
            if existing is not None
            else item.get("subject_id")
        )
        student_id = (
            existing.student_id
            if existing is not None
            else item.get("student_id")
        )

        if not allowed_subject(subject_id):
            raise PermissionDenied(
                "Không được ghi danh vào môn này."
            )

        # Không cho chuyển enrollment sang khóa khác.
        if existing is not None:
            if item.get("subject_id", subject_id) != subject_id:
                raise PermissionDenied(
                    "Không được đổi môn của enrollment."
                )
            if item.get("student_id", student_id) != student_id:
                raise PermissionDenied(
                    "Không được đổi sinh viên của enrollment."
                )

        if student_id and item.get("deleted_at") is None:
            batch_student_ids.add(student_id)

    owned_student_ids = select(Enrollment.student_id).where(
        Enrollment.subject_id.in_(accessible_subject_ids()),
        Enrollment.deleted_at.is_(None)
    )

    for table_name, item, existing in changes:

        # Không cho sửa khóa nghiệp vụ của bản ghi đã tồn tại.
        identity_fields = {
            "admin": ("admin_id",),
            "subjects": ("subject_id",),
            "students": ("student_id",),
            "enrollments": ("student_id", "subject_id"),
            "checkin_history": (),
            "email_recipients": ("email_id",),
        }

        if existing is not None:
            for field in identity_fields.get(table_name, ()):
                if field in item and item[field] != getattr(existing, field):
                    raise PermissionDenied(
                        f"Không được thay đổi khóa {field}."
                    )

            if (
                table_name != "students"
                and item.get("uuid") is not None
                and item["uuid"] != existing.uuid
            ):
                raise PermissionDenied(
                    "Không được thay đổi UUID của bản ghi."
                )

        if table_name == "subjects":
            subject_id = (
                existing.subject_id
                if existing is not None
                else item.get("subject_id")
            )

            if existing is not None:
                if not can_access_subject(subject_id):
                    raise PermissionDenied(
                        "Không được sửa môn của giảng viên khác."
                    )

            if item.get("instructor_id", admin_id) != admin_id:
                raise PermissionDenied(
                    "Không được chuyển môn cho giảng viên khác."
                )

            if existing is not None:
                if (
                    "created_by" in item
                    and item["created_by"] != existing.created_by
                ):
                    raise PermissionDenied(
                        "Không được thay đổi người tạo môn."
                    )

        elif table_name == "students":
            student_id = (
                existing.student_id
                if existing is not None
                else item.get("student_id")
            )

            if not student_id:
                raise PermissionDenied("Thiếu mã sinh viên.")

            belongs_to_owned_subject = db.session.execute(
                select(Enrollment.student_id)
                .where(
                    Enrollment.student_id == student_id,
                    Enrollment.subject_id.in_(
                        accessible_subject_ids()
                    ),
                    Enrollment.deleted_at.is_(None)
                )
                .limit(1)
            ).first() is not None

            if (
                not belongs_to_owned_subject
                and student_id not in batch_student_ids
            ):
                raise PermissionDenied(
                    "Sinh viên không thuộc môn được quản lý."
                )

        elif table_name in (
            "enrollments",
            "checkin_history",
            "email_recipients"
        ):
            subject_id = (
                existing.subject_id
                if existing is not None
                else item.get("subject_id")
            )

            if not allowed_subject(subject_id):
                raise PermissionDenied(
                    "Không có quyền ghi dữ liệu môn học."
                )

            if (
                "subject_id" in item
                and item["subject_id"] != subject_id
            ):
                raise PermissionDenied(
                    "Không được chuyển dữ liệu sang môn khác."
                )

        elif table_name == "admin":
            if existing is None or existing.admin_id != admin_id:
                raise PermissionDenied(
                    "ADMIN chỉ được sửa hồ sơ chính mình."
                )

            # Chỉ cho đồng bộ trường hồ sơ thông thường.
            allowed_fields = {
                "admin_id", "uuid", "updated_at", "seq",
                "full_name", "date_of_birth", "phone",
                "gender", "photo_path", "description",
                "is_first_login", "has_iris",
                "face_embedding"
            }

            if set(item) - allowed_fields:
                raise PermissionDenied(
                    "Có trường tài khoản không được phép sửa qua sync."
                )

        else:
            raise PermissionDenied(
                f"Bảng {table_name} không được phép đồng bộ."
            )
