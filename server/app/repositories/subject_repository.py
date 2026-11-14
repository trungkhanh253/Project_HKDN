from app import db
from app.models import Subject
from app.repositories.base_repository import BaseRepository
import sqlalchemy as sa

class SubjectRepository(BaseRepository):
    @staticmethod
    def get_by_id(subject_id: str, include_deleted: bool = False):
        query = Subject.query.filter_by(subject_id=subject_id)
        if not include_deleted:
            query = query.filter(Subject.deleted_at.is_(None))
        return query.first()

    @staticmethod
    def get_by_instructor(instructor_id: str):
        return Subject.query.filter_by(instructor_id=instructor_id, deleted_at=None).all()

    @staticmethod
    def list_paginated(q: str = None, sort: str = None, limit: int = 10, offset: int = 0, instructor_id: str = None):
        query = Subject.query.filter(Subject.deleted_at.is_(None))
        if instructor_id:
            query = query.filter(Subject.instructor_id == instructor_id)

        if q and q.strip():
            kw = f"%{q.strip()}%"
            query = query.filter(
                sa.or_(
                    Subject.subject_id.ilike(kw),
                    Subject.subject_name.ilike(kw),
                    Subject.time_slot.ilike(kw),
                )
            )

        total = query.count()

        if sort:
            parts = sort.split(":")
            field_name = parts[0].strip().lower()
            order_dir = parts[1].strip().lower() if len(parts) > 1 else "asc"
            col = getattr(Subject, field_name, None)
            if col is not None:
                query = query.order_by(col.desc() if order_dir == "desc" else col.asc())
            else:
                query = query.order_by(Subject.subject_id.asc())
        else:
            query = query.order_by(Subject.subject_id.asc())

        items = query.offset(offset).limit(limit).all()
        return items, total

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
