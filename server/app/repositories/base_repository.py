import uuid
from datetime import datetime, timezone
from app import db


class BaseRepository:
    """Repository dùng chung hỗ trợ các trường metadata đồng bộ dữ liệu"""

    @staticmethod
    def generate_uuid():
        return str(uuid.uuid4())

    @staticmethod
    def get_current_time():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def parse_datetime(value):
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc).replace(tzinfo=None)
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(text, fmt)
                    except ValueError:
                        continue
                raise ValueError(f"Định dạng thời gian không hợp lệ: {value}")
        raise ValueError(f"Định dạng thời gian không hợp lệ: {value}")

    @staticmethod
    def soft_delete(model_instance):
        """Xóa mềm (Soft Delete) phục vụ đồng bộ dữ liệu 2 chiều"""
        now = BaseRepository.get_current_time()
        model_instance.deleted_at = now
        model_instance.updated_at = now
        db.session.commit()
        return model_instance
