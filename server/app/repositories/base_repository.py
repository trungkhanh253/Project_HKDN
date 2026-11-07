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
        return datetime.now(timezone.utc)

    @staticmethod
    def soft_delete(model_instance):
        """Xóa mềm (Soft Delete) phục vụ đồng bộ dữ liệu 2 chiều"""
        model_instance.deleted_at = BaseRepository.get_current_time()
        model_instance.updated_at = BaseRepository.get_current_time()
        db.session.commit()
        return model_instance