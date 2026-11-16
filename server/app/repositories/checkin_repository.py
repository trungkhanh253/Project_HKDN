from app import db
from app.models import CheckinHistory, Student, Subject, Enrollment
from app.repositories.base_repository import BaseRepository
import sqlalchemy as sa

class CheckinRepository(BaseRepository):
    @staticmethod
    def record_checkin(student_id: str, subject_id: str, checkin_time: str, checkin_date: str, uuid_str: str = None):
        """
        Ghi nhận điểm danh có kiểm tra lũy đẳng (chống trùng uuid).
        """
        now = BaseRepository.get_current_time()
        final_uuid = uuid_str or BaseRepository.generate_uuid()

        # Kiểm tra nếu uuid đã tồn tại
        existing = CheckinHistory.query.filter_by(uuid=final_uuid).first()
        if existing:
            return existing, False  # (bản ghi, is_created)

        checkin = CheckinHistory(
            student_id=student_id,
            subject_id=subject_id,
            checkin_time=checkin_time,
            checkin_date=checkin_date,
            uuid=final_uuid,
            updated_at=now,
        )
        db.session.add(checkin)
        db.session.commit()
        return checkin, True

    @staticmethod
    def get_history(subject_id: str = None, checkin_date: str = None, student_id: str = None, limit: int = 100, offset: int = 0):
        query = CheckinHistory.query.filter(CheckinHistory.deleted_at.is_(None))

        if subject_id:
            query = query.filter(CheckinHistory.subject_id == subject_id)
        if checkin_date:
            query = query.filter(CheckinHistory.checkin_date == checkin_date)
        if student_id:
            query = query.filter(CheckinHistory.student_id == student_id)

        total = query.count()
        items = query.order_by(CheckinHistory.checkin_id.desc()).offset(offset).limit(limit).all()
        return items, total
