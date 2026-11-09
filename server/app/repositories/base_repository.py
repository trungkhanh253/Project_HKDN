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
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e11:  # Epoch milliseconds từ Android System.currentTimeMillis()
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit():
                ts = float(text)
                if ts > 1e11:
                    ts = ts / 1000.0
                return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
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
    def to_epoch_ms(dt) -> int:
        if dt is None:
            return 0
        if isinstance(dt, (int, float)):
            return int(dt if dt > 1e11 else dt * 1000)
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        return 0

    @staticmethod
    def soft_delete(model_instance):
        """Xóa mềm (Soft Delete) phục vụ đồng bộ dữ liệu 2 chiều"""
        now = BaseRepository.get_current_time()
        model_instance.deleted_at = now
        model_instance.updated_at = now
        db.session.commit()
        return model_instance

    @staticmethod
    def find_nearest_by_embedding(model_class, query_embedding, limit: int = 1, max_distance: float = None):
        """
        Truy vấn tìm kiếm sinh trắc học khuôn mặt gần nhất bằng pgvector (Cosine Distance <=>).
        Chỉ xét các bản ghi chưa xóa mềm (deleted_at IS NULL) và có face_embedding khác NULL.
        """
        if not hasattr(model_class, "face_embedding"):
            raise ValueError(f"Model {model_class.__name__} không có trường face_embedding.")
        if not isinstance(query_embedding, (list, tuple)) or len(query_embedding) != 192:
            raise ValueError("Vector truy vấn (query_embedding) phải có đúng 192 chiều.")

        vec = [float(x) for x in query_embedding]
        distance_expr = model_class.face_embedding.cosine_distance(vec)

        query = model_class.query.filter(
            model_class.deleted_at.is_(None),
            model_class.face_embedding.isnot(None),
        )
        if max_distance is not None:
            query = query.filter(distance_expr <= float(max_distance))

        return query.order_by(distance_expr.asc()).limit(max(1, int(limit))).all()

