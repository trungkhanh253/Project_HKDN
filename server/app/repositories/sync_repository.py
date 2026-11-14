import hashlib
from datetime import timedelta
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
from app.permissions import (
    PermissionDenied,
    require_sync_batch_access,
)
from app.permissions import filter_accessible

# Thứ tự bảng từ cha -> con để đảm bảo khóa ngoại khi đồng bộ
SYNC_TABLES = [
    ("admin", Admin),
    ("subjects", Subject),
    ("students", Student),
    ("enrollments", Enrollment),
    ("checkin_history", CheckinHistory),
    ("email_recipients", EmailRecipient),
]

TABLE_NAME_ALIASES = {
    "admin": ("admin", Admin),
    "admins": ("admin", Admin),
    "subject": ("subjects", Subject),
    "subjects": ("subjects", Subject),
    "student": ("students", Student),
    "students": ("students", Student),
    "enrollment": ("enrollments", Enrollment),
    "enrollments": ("enrollments", Enrollment),
    "checkin_history": ("checkin_history", CheckinHistory),
    "email_recipient": ("email_recipients", EmailRecipient),
    "email_recipients": ("email_recipients", EmailRecipient),
}

TABLE_PRIORITY = {name: idx for idx, (name, _) in enumerate(SYNC_TABLES)}


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
    def pull_all_changes(after_seq: int = 0, limit: int = 100, flat_changes: bool = False) -> dict:
        """
        Lấy thay đổi trên toàn bộ 6 bảng có seq > after_seq, phân trang theo global seq.
        - Khi flat_changes=False (mặc định khi gọi qua after_seq): trả về changes gom nhóm theo tên bảng.
        - Khi flat_changes=True (khi Android SyncManager gọi qua since_seq): trả về changes dạng danh sách SyncChange
          kèm new_seq, has_more tương thích 100% với SyncPullResponse.java.
        """
        limit = max(1, min(int(limit), 500))
        after_seq = max(0, int(after_seq))

        # Thu thập các cặp (seq, table_name, record) có seq > after_seq
        candidates = []
        for table_name, model_cls in SYNC_TABLES:
            query = model_cls.query.filter(
                model_cls.seq > after_seq
            )

            query = filter_accessible(query, model_cls)

            rows = (
                query
                .order_by(model_cls.seq.asc())
                .limit(limit + 1)
                .all()
            )
            for row in rows:
                candidates.append((int(row.seq), table_name, row))

        candidates.sort(key=lambda item: item[0])
        has_more = len(candidates) > limit
        selected = candidates[:limit]

        next_seq = selected[-1][0] if selected else after_seq
        latest_seq = SyncRepository.get_latest_seq()

        if flat_changes:
            change_list = []
            for seq_val, table_name, row in selected:
                op = "DELETE" if row.deleted_at is not None else "INSERT"
                change_list.append(
                    {
                        "change_id": row.uuid,
                        "uuid": row.uuid,
                        "table_name": table_name,
                        "operation": op,
                        "payload": SyncRepository._to_safe_dict(row),
                        "updated_at": BaseRepository.to_epoch_ms(row.updated_at),
                        "seq": seq_val,
                    }
                )
            return {
                "new_seq": next_seq,
                "after_seq": after_seq,
                "next_seq": next_seq,
                "latest_seq": latest_seq,
                "limit": limit,
                "has_more": has_more,
                "changes": change_list,
            }

        changes = {table_name: [] for table_name, _ in SYNC_TABLES}
        for _, table_name, row in selected:
            changes[table_name].append(
            SyncRepository._to_safe_dict(row)
        )

        return {
            "after_seq": after_seq,
            "next_seq": next_seq,
            "new_seq": next_seq,
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
            # UUID đã được kiểm tra ở đầu hàm.
            # Không sử dụng checkin_id từ Android để tìm bản ghi.
            return None

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
    def _authorize_push_changes(changes):
        from app.permissions import require_sync_batch_access

        normalized = []

        for table_name, item in changes:
            if not isinstance(item, dict):
                raise ValueError(
                    "Dữ liệu đồng bộ phải là JSON object."
                )

            if table_name not in TABLE_NAME_ALIASES:
                raise ValueError(
                    f"Bảng '{table_name}' không hợp lệ."
                )

            canonical_name, model_cls = TABLE_NAME_ALIASES[
                table_name
            ]

            existing = SyncRepository._find_existing(
                canonical_name,
                model_cls,
                item
            )


            # Ngăn UUID trỏ tới một bản ghi nhưng
            # khóa nghiệp vụ lại trỏ tới bản ghi khác.
            if existing is not None:
                identity_fields = {
                    "admin": ("admin_id",),
                    "subjects": ("subject_id",),
                    "students": ("student_id",),
                    "enrollments": (
                        "student_id", "subject_id"
                    ),
                    "checkin_history": ("checkin_id",),
                    "email_recipients": ("email_id",),
                }

                for field in identity_fields.get(
                    canonical_name, ()
                ):
                    supplied = item.get(field)
                    actual = getattr(existing, field)

                    if supplied is not None and supplied != actual:
                        raise PermissionDenied(
                            f"Không được thay đổi {field} "
                            f"của bản ghi hiện có."
                        )


            normalized.append(
                (canonical_name, item, existing)
            )

        require_sync_batch_access(normalized)


    @staticmethod
    def _push_outbox_change_list(changes_list: list) -> dict:
        """
        Xử lý danh sách SyncChange từ Android SyncPushRequest:
        [{"change_id", "uuid", "table_name", "operation": "INSERT"|"UPDATE"|"DELETE", "payload": {...}, "updated_at"}]
        Hỗ trợ partial success bằng SAVEPOINT (begin_nested) cho từng bản ghi.
        """
        applied_counts = {t: 0 for t, _ in SYNC_TABLES}
        skipped_counts = {t: 0 for t, _ in SYNC_TABLES}
        synced_change_ids = []
        failed_change_ids = []
        synced_uuids = []
        failed_uuids = []
        errors = []

        authorization_changes = []

        for change in changes_list:
            if not isinstance(change, dict):
                raise ValueError("Thay đổi không hợp lệ.")

            table_name = str(
                change.get("table_name") or ""
            ).strip().lower()

            item = dict(
                change.get("payload")
                if isinstance(change.get("payload"), dict)
                else {}
            )

            if change.get("uuid"):
                item["uuid"] = str(change["uuid"])

            if change.get("operation", "").upper() == "DELETE":
                item["deleted_at"] = (
                    change.get("updated_at") or "DELETE"
                )

            authorization_changes.append((table_name, item))

        SyncRepository._authorize_push_changes(
            authorization_changes
        )

        # Sắp xếp theo thứ tự bảng cha -> con để hạn chế lỗi khóa ngoại khi cùng lô
        indexed_changes = list(enumerate(changes_list))

        def _sort_key(pair):
            idx, chg = pair
            if not isinstance(chg, dict):
                return (999, idx)
            raw_tbl = str(chg.get("table_name") or "").strip().lower()
            canonical_tbl = TABLE_NAME_ALIASES.get(raw_tbl, (raw_tbl, None))[0]
            op = str(chg.get("operation") or "").strip().upper()
            # Nếu là DELETE thì xóa bảng con trước, nếu INSERT/UPDATE thì bảng cha trước
            priority = TABLE_PRIORITY.get(canonical_tbl, 99)
            if op == "DELETE":
                priority = 100 - priority
            return (priority, idx)

        indexed_changes.sort(key=_sort_key)

        for _, change in indexed_changes:
            if not isinstance(change, dict):
                raise ValueError("Mỗi phần tử trong 'changes' phải là một JSON object.")

            change_id = change.get("change_id") or change.get("uuid")
            rec_uuid = change.get("uuid") or change_id
            raw_table = str(change.get("table_name") or "").strip().lower()
            operation = str(change.get("operation") or "UPSERT").strip().upper()
            inner_payload = change.get("payload") if isinstance(change.get("payload"), dict) else {}

            if raw_table not in TABLE_NAME_ALIASES:
                err_msg = f"Bảng '{raw_table}' không hợp lệ."
                errors.append(err_msg)
                if change_id:
                    failed_change_ids.append(str(change_id))
                if rec_uuid:
                    failed_uuids.append(str(rec_uuid))
                continue

            table_name, model_cls = TABLE_NAME_ALIASES[raw_table]
            merged_item = dict(inner_payload)
            if rec_uuid:
                merged_item["uuid"] = str(rec_uuid)
            if change.get("updated_at") is not None:
                merged_item["updated_at"] = change.get("updated_at")

            now = BaseRepository.get_current_time()
            incoming_updated_at = BaseRepository.parse_datetime(merged_item.get("updated_at")) or now
            if operation == "DELETE":
                incoming_deleted_at = BaseRepository.parse_datetime(merged_item.get("deleted_at")) or incoming_updated_at
                merged_item["deleted_at"] = incoming_deleted_at
            else:
                incoming_deleted_at = BaseRepository.parse_datetime(merged_item.get("deleted_at"))

            try:
                with db.session.begin_nested():
                    if "face_embedding" in merged_item and merged_item["face_embedding"] is not None:
                        merged_item["face_embedding"] = _validate_embedding(merged_item["face_embedding"])

                    existing = SyncRepository._find_existing(table_name, model_cls, merged_item)

                    if existing is not None:
                        if (
                            incoming_updated_at is not None
                            and existing.updated_at is not None
                            and incoming_updated_at < existing.updated_at
                        ):
                            skipped_counts[table_name] += 1
                        else:
                            if operation == "DELETE":
                                existing.deleted_at = incoming_deleted_at
                                existing.updated_at = incoming_updated_at
                            else:
                                SyncRepository._apply_fields(
                                    table_name,
                                    existing,
                                    merged_item,
                                    incoming_updated_at=incoming_updated_at,
                                    incoming_deleted_at=incoming_deleted_at,
                                    is_new=False,
                                )
                            applied_counts[table_name] += 1
                    else:
                        if operation == "DELETE":
                            # Bản ghi cần xóa chưa từng tồn tại trên Server -> coi như đã xử lý xong
                            skipped_counts[table_name] += 1
                        else:
                            new_obj = model_cls()
                            SyncRepository._apply_fields(
                                table_name,
                                new_obj,
                                merged_item,
                                incoming_updated_at=incoming_updated_at,
                                incoming_deleted_at=incoming_deleted_at,
                                is_new=True,
                            )
                            db.session.add(new_obj)
                            applied_counts[table_name] += 1

                    db.session.flush()

                if change_id:
                    synced_change_ids.append(str(change_id))
                if rec_uuid:
                    synced_uuids.append(str(rec_uuid))

            except (IntegrityError, DataError, ValueError) as exc:
                orig_msg = str(getattr(exc, "orig", exc))
                errors.append(orig_msg)
                if change_id:
                    failed_change_ids.append(str(change_id))
                if rec_uuid:
                    failed_uuids.append(str(rec_uuid))

        db.session.commit()
        latest_seq = SyncRepository.get_latest_seq()

        return {
            "status": "ok",
            "success": len(failed_change_ids) == 0 or len(synced_change_ids) > 0,
            "synced_change_ids": synced_change_ids,
            "failed_change_ids": failed_change_ids,
            "synced_uuids": synced_uuids,
            "failed_uuids": failed_uuids,
            "error_message": "; ".join(errors) if errors else None,
            "applied": applied_counts,
            "skipped": skipped_counts,
            "latest_seq": latest_seq,
        }

    @staticmethod
    def push_changes(payload: dict) -> dict:
        """
        Xử lý đẩy dữ liệu (Upsert + Soft Delete) cho 6 bảng theo thứ tự cha -> con.
        Chiến lược xung đột: Last-Write-Wins (LWW) dựa trên updated_at.
        Hỗ trợ đồng thời 2 định dạng:
        1. Định dạng Outbox List từ Android SyncManager: {"device_id": ..., "changes": [{"uuid", "table_name", "operation", "payload", "updated_at"}]}
        2. Định dạng Object gom theo bảng: {"students": [...], "subjects": [...]} (hoặc {"changes": {"students": [...]}})
        """
        if not isinstance(payload, dict):
            raise ValueError("Body JSON phải là một object.")

        if isinstance(payload.get("changes"), list):
            return SyncRepository._push_outbox_change_list(payload["changes"])

        changes_root = payload.get("changes") if isinstance(payload.get("changes"), dict) else payload

        allowed_tables = {name for name, _ in SYNC_TABLES}

        unknown_tables = set(changes_root) - allowed_tables

        if unknown_tables:
            raise ValueError(
                f"Bảng đồng bộ không hợp lệ: {sorted(unknown_tables)}"
            )

        authorization_changes = []

        for table_name, _ in SYNC_TABLES:
            records = changes_root.get(table_name, [])

            if records is None:
                continue

            if not isinstance(records, list):
                raise ValueError(
                    f"Trường '{table_name}' phải là danh sách."
                )

            for item in records:
                authorization_changes.append(
                    (table_name, item)
                )

        SyncRepository._authorize_push_changes(
            authorization_changes
        )

        applied_counts = {t: 0 for t, _ in SYNC_TABLES}
        skipped_counts = {t: 0 for t, _ in SYNC_TABLES}
        synced_uuids = []

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
                    # Nếu client đẩy lên một thực thể mới (khác UUID) cho cùng khóa tự nhiên -> cho phép khởi tạo lại
                    is_new_uuid_entity = bool(
                        item.get("uuid") and item.get("uuid") != existing.uuid
                    )
                    # Last-Write-Wins (LWW): nếu cùng thực thể mà client gửi updated_at cũ hơn trên server -> bỏ qua
                    if (
                        incoming_updated_at is not None
                        and existing.updated_at is not None
                        and incoming_updated_at < existing.updated_at
                    ):
                        skipped_counts[table_name] += 1
                        if getattr(existing, "uuid", None):
                            synced_uuids.append(existing.uuid)
                        continue

                    if (
                        incoming_updated_at is not None
                        and existing.updated_at is not None
                        and incoming_updated_at == existing.updated_at
                    ):
                        # Tránh trigger bump_sync_metadata hiểu nhầm NEW.updated_at = OLD.updated_at rồi ghi đè thành CURRENT_TIMESTAMP
                        incoming_updated_at = incoming_updated_at + timedelta(microseconds=1)

                    SyncRepository._apply_fields(
                        table_name,
                        existing,
                        item,
                        incoming_updated_at=incoming_updated_at,
                        incoming_deleted_at=incoming_deleted_at,
                        is_new=False,
                    )
                    target_obj = existing
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
                    target_obj = new_obj

                db.session.flush()
                applied_counts[table_name] += 1
                if getattr(target_obj, "uuid", None):
                    synced_uuids.append(target_obj.uuid)

        db.session.commit()
        latest_seq = SyncRepository.get_latest_seq()

        return {
            "status": "ok",
            "success": True,
            "synced_change_ids": synced_uuids,
            "failed_change_ids": [],
            "synced_uuids": synced_uuids,
            "failed_uuids": [],
            "error_message": None,
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
            obj.uuid = str(item.get("uuid") or item.get("change_id") or BaseRepository.generate_uuid())

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


    @staticmethod
    def _to_safe_dict(row):
        data = row.to_dict()

        for field in (
            "password",
            "reset_token",
            "expire_at",
            "checkin_password",
            "face_embedding",
        ):
            data.pop(field, None)

        return data
