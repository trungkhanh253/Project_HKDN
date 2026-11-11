from app import db
from app.models import Subject
from app.repositories.base_repository import BaseRepository

class SubjectRepository(BaseRepository):
    @staticmethod
    def get_by_id(subject_id: str):
        return Subject.query.filter_by(subject_id=subject_id, deleted_at=None).first()

    @staticmethod
    def get_by_instructor(instructor_id: str):
        return Subject.query.filter_by(instructor_id=instructor_id, deleted_at=None).all()

    @staticmethod
    def create(subject_data: dict):
        subject = Subject(
            subject_id=subject_data['subject_id'],
            subject_name=subject_data['subject_name'],
            time_slot=subject_data.get('time_slot'),
            created_by=subject_data.get('created_by'),
            instructor_id=subject_data.get('instructor_id'),
            subject_status=subject_data.get('subject_status', 'ACTIVE'),
            created_at=subject_data.get('created_at'),
            semester_start_date=subject_data.get('semester_start_date'),
            semester_end_date=subject_data.get('semester_end_date'),
            uuid=subject_data.get('uuid', BaseRepository.generate_uuid()),
            updated_at=BaseRepository.get_current_time()
        )
        db.session.add(subject)
        db.session.commit()
        return subject
