from app import db
from app.models import CheckinHistory
from app.repositories.base_repository import BaseRepository

class CheckinRepository(BaseRepository):
    @staticmethod
    def record_checkin(student_id: str, subject_id: str, checkin_time: str, checkin_date: str):
        checkin = CheckinHistory(
            student_id=student_id,
            subject_id=subject_id,
            checkin_time=checkin_time,
            checkin_date=checkin_date,
            uuid=BaseRepository.generate_uuid(),
            updated_at=BaseRepository.get_current_time()
        )
        db.session.add(checkin)
        db.session.commit()
        return checkin

    @staticmethod
    def get_history_by_subject(subject_id: str, checkin_date: str = None):
        query = CheckinHistory.query.filter_by(subject_id=subject_id, deleted_at=None)
        if checkin_date:
            query = query.filter_by(checkin_date=checkin_date)
        return query.order_by(CheckinHistory.checkin_id.desc()).all()
