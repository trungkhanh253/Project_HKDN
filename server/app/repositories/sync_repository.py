import hashlib
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, DataError
from app import db
from app.models import (
    Admin,
    Subject,
    Student,
    Enrollment,
    CheckinHistory,
    EmailRecipient,
)
from app.repositories.base_repository import BaseRepository

# Thứ tự bảng từ cha -> con để đảm bảo khóa ngoại khi đồng bộ
SYNC_TABLES = [
    ("admin", Admin),
    ("subjects", Subject),
    ("students", Student),
    ("enrollments", Enrollment),
    ("checkin_history", CheckinHistory),
    ("email_recipients", EmailRecipient),
]


def _hash_password_if_needed(raw_password: str) -> str:
    if not raw_password:
        return hashlib.sha256(b"123456").hexdigest()
    # Nếu đã là chuỗi SHA-256 hex (64 ký tự hex) thì giữ nguyên
    if len(raw_password) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw_password):
        return raw_password.lower()
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


def _validate_embedding(emb):
    if emb is None:
        return None
    if not isinstance(emb, (list, tuple)) or len(emb) != 192:
        raise ValueError("Trường face_embedding phải là mảng số thực có đúng 192 chiều.")
    try:
        return [float(x) for x in emb]
    except (TypeError, ValueError) as exc:
        raise ValueError("Trường face_embedding chứa giá trị không phải số.") from exc


class SyncRepository(BaseRepository):
    @staticmethod
    def pull_changes_by_seq(model_class, after_seq: int, limit: int = 100):
        """
        Lấy danh sách bản ghi thay đổi của một bảng dựa vào cột seq lớn hơn after_seq.
        Bao gồm cả bản ghi đã xóa mềm (deleted_at != None).
        """
        return (
            model_class.query
            .filter(model_class.seq > after_seq)
            .order_by(model_class.seq.asc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_latest_seq() -> int:
        max_seqs = []
        for _, model_cls in SYNC_TABLES:
            val = db.session.query(sa.func.max(model_cls.seq)).scalar()
            if val is not None:
                max_seqs.append(int(val))
        return max(max_seqs) if max_seqs else 0

    @staticmethod
    def pull_all_changes(after_seq: int = 0, limit: int = 100) -> dict:
        """
        Lấy thay đổi trên toàn bộ 6 bảng có seq > after_seq, phân trang theo global seq.
        """
        limit = max(1, min(int(limit), 500))
        after_seq = max(0, int(after_seq))

        # Thu thập các cặp (seq, table_name, record) có seq > after_seq
        candidates = []
        for table_name, model_cls in SYNC_TABLES:
            rows = (
                model_cls.query
                .filter(model_cls.seq > after_seq)
                .order_by(model_cls.seq.asc())
                .limit(limit + 1)
                .all()
            )
            for row in rows:
                candidates.append((int(row.seq), table_name, row))

        candidates.sort(key=lambda item: item[0])
        has_more = len(candidates) > limit
        selected = candidates[:limit]

        changes = {table_name: [] for table_name, _ in SYNC_TABLES}
        for _, table_name, row in selected:
            changes[table_name].append(row.to_dict())

        next_seq = selected[-1][0] if selected else after_seq
        latest_seq = SyncRepository.get_latest_seq()

        return {
            "after_seq": after_seq,
            "next_seq": next_seq,
            "latest_seq": latest_seq,
            "limit": limit,
            "has_more": has_more,
            "changes": changes,
        }

    @staticmethod
    def _find_existing(table_name: str, model_cls, item: dict):
        rec_uuid = item.get("uuid")
        if rec_uuid:
            found = model_cls.query.filter_by(uuid=rec_uuid).first()
            if found:
                return found

        if table_name == "admin":
            if item.get("admin_id"):
                found = Admin.query.filter_by(admin_id=item["admin_id"]).first()
                if found:
                    return found
            if item.get("email"):
                return Admin.query.filter_by(email=item["email"]).first()

        elif table_name == "subjects":
            if item.get("subject_id"):
                return Subject.query.filter_by(subject_id=item["subject_id"]).first()

        elif table_name == "students":
            if item.get("student_id"):
                return Student.query.filter_by(student_id=item["student_id"]).first()

        elif table_name == "enrollments":
            if item.get("student_id") and item.get("subject_id"):
                return Enrollment.query.filter_by(
                    student_id=item["student_id"],
                    subject_id=item["subject_id"],
                ).first()

        elif table_name == "checkin_history":
            if item.get("checkin_id") is not None:
                return CheckinHistory.query.filter_by(checkin_id=item["checkin_id"]).first()

        elif table_name == "email_recipients":
            if item.get("subject_id") and item.get("email_address"):
                found = EmailRecipient.query.filter_by(
                    subject_id=item["subject_id"],
                    email_address=item["email_address"],
                ).first()
                if found:
                    return found
            if item.get("email_id") is not None:
                return EmailRecipient.query.filter_by(email_id=item["email_id"]).first()

        return None

    @staticmethod
    def push_changes(payload: dict) -> dict:
        """
        Xử lý đẩy dữ liệu (Upsert + Soft Delete) cho 6 bảng theo thứ tự cha -> con.
        Chiến lược xung đột: Last-Write-Wins (LWW) dựa trên updated_at.
        """
        if not isinstance(payload, dict):
            raise ValueError("Body JSON phải là một object.")

        changes_root = payload.get("changes") if isinstance(payload.get("changes"), dict) else payload

        applied_counts = {t: 0 for t, _ in SYNC_TABLES}
        skipped_counts = {t: 0 for t, _ in SYNC_TABLES}

        for table_name, model_cls in SYNC_TABLES:
            records = changes_root.get(table_name, [])
            if records is None:
                continue
            if not isinstance(records, list):
                raise ValueError(f"Trường '{table_name}' phải là một danh sách (array).")

            for item in records:
                if not isinstance(item, dict):
                    raise ValueError(f"Bản ghi trong '{table_name}' phải là một object JSON.")

                incoming_updated_at = BaseRepository.parse_datetime(item.get("updated_at"))
                incoming_deleted_at = BaseRepository.parse_datetime(item.get("deleted_at"))
                if "face_embedding" in item and item["face_embedding"] is not None:
                    item = dict(item)
                    item["face_embedding"] = _validate_embedding(item["face_embedding"])

                existing = SyncRepository._find_existing(table_name, model_cls, item)

                if existing is not None:
                    # Last-Write-Wins (LWW): nếu client gửi updated_at cũ hơn bản ghi hiện có trên server -> bỏ qua
                    if (
                        incoming_updated_at is not None
                        and existing.updated_at is not None
                        and incoming_updated_at < existing.updated_at
                    ):
                        skipped_counts[table_name] += 1
                        continue

                    SyncRepository._apply_fields(
                        table_name,
                        existing,
                        item,
                        incoming_updated_at=incoming_updated_at,
                        incoming_deleted_at=incoming_deleted_at,
                        is_new=False,
                    )
                else:
                    new_obj = model_cls()
                    SyncRepository._apply_fields(
                        table_name,
                        new_obj,
                        item,
                        incoming_updated_at=incoming_updated_at,
                        incoming_deleted_at=incoming_deleted_at,
                        is_new=True,
                    )
                    db.session.add(new_obj)

                db.session.flush()
                applied_counts[table_name] += 1

        db.session.commit()
        latest_seq = SyncRepository.get_latest_seq()

        return {
            "status": "ok",
            "applied": applied_counts,
            "skipped": skipped_counts,
            "latest_seq": latest_seq,
        }

    @staticmethod
    def _apply_fields(
        table_name: str,
        obj,
        item: dict,
        incoming_updated_at=None,
        incoming_deleted_at=None,
        is_new: bool = False,
    ):
        now = BaseRepository.get_current_time()
        if is_new or not getattr(obj, "uuid", None):
            obj.uuid = item.get("uuid") or BaseRepository.generate_uuid()
        elif item.get("uuid"):
            obj.uuid = item["uuid"]

        obj.updated_at = incoming_updated_at or now
        if "deleted_at" in item:
            obj.deleted_at = incoming_deleted_at
        elif is_new:
            obj.deleted_at = None

        if table_name == "admin":
            admin_id = item.get("admin_id") or getattr(obj, "admin_id", None)
            email = item.get("email") or getattr(obj, "email", None)
            full_name = item.get("full_name") or getattr(obj, "full_name", None)
            if not admin_id or not email or not full_name:
                raise ValueError("Bảng 'admin' yêu cầu bắt buộc: admin_id, email, full_name.")
            obj.admin_id = str(admin_id)
            obj.email = str(email)
            obj.full_name = str(full_name)
            if "password" in item and item["password"]:
                obj.password = _hash_password_if_needed(str(item["password"]))
            elif is_new and not getattr(obj, "password", None):
                obj.password = _hash_password_if_needed("123456")
            for field in (
                "date_of_birth",
                "phone",
                "gender",
                "photo_path",
                "description",
                "role",
                "admin_code",
                "reset_token",
                "expire_at",
                "is_first_login",
                "has_iris",
                "face_embedding",
            ):
                if field in item:
                    setattr(obj, field, item[field])

        elif table_name == "subjects":
            subject_id = item.get("subject_id") or getattr(obj, "subject_id", None)
            subject_name = item.get("subject_name") or getattr(obj, "subject_name", None)
            if not subject_id or not subject_name:
                raise ValueError("Bảng 'subjects' yêu cầu bắt buộc: subject_id, subject_name.")
            obj.subject_id = str(subject_id)
            obj.subject_name = str(subject_name)
            for field in (
                "time_slot",
                "created_by",
                "instructor_id",
                "subject_status",
                "created_at",
                "semester_start_date",
                "semester_end_date",
            ):
                if field in item:
                    setattr(obj, field, item[field])

        elif table_name == "students":
            student_id = item.get("student_id") or getattr(obj, "student_id", None)
            if not student_id:
                raise ValueError("Bảng 'students' yêu cầu bắt buộc: student_id.")
            obj.student_id = str(student_id)
            for field in (
                "full_name",
                "email",
                "phone",
                "photo_path",
                "checkin_password",
                "face_embedding",
            ):
                if field in item:
                    setattr(obj, field, item[field])

        elif table_name == "enrollments":
            student_id = item.get("student_id") or getattr(obj, "student_id", None)
            subject_id = item.get("subject_id") or getattr(obj, "subject_id", None)
            if not student_id or not subject_id:
                raise ValueError("Bảng 'enrollments' yêu cầu bắt buộc: student_id, subject_id.")
            obj.student_id = str(student_id)
            obj.subject_id = str(subject_id)
            if "enrollment_status" in item:
                obj.enrollment_status = item["enrollment_status"]

        elif table_name == "checkin_history":
            student_id = item.get("student_id") or getattr(obj, "student_id", None)
            subject_id = item.get("subject_id") or getattr(obj, "subject_id", None)
            if not student_id or not subject_id:
                raise ValueError("Bảng 'checkin_history' yêu cầu bắt buộc: student_id, subject_id.")
            obj.student_id = str(student_id)
            obj.subject_id = str(subject_id)
            for field in ("checkin_time", "checkin_date"):
                if field in item:
                    setattr(obj, field, item[field])

        elif table_name == "email_recipients":
            subject_id = item.get("subject_id") or getattr(obj, "subject_id", None)
            email_address = item.get("email_address") or getattr(obj, "email_address", None)
            if not subject_id or not email_address:
                raise ValueError("Bảng 'email_recipients' yêu cầu bắt buộc: subject_id, email_address.")
            obj.subject_id = str(subject_id)
            obj.email_address = str(email_address)
            for field in ("recipient_name", "added_date", "is_selected"):
                if field in item:
                    setattr(obj, field, item[field])
