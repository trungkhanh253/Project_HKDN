from app import db
from app.models import Subject, Student, Enrollment
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

    @staticmethod
    def update(subject_id: str, update_data: dict):
        subject = SubjectRepository.get_by_id(subject_id)
        if not subject:
            return None
        allowed_fields = [
            "subject_name",
            "time_slot",
            "instructor_id",
            "subject_status",
            "semester_start_date",
            "semester_end_date",
        ]
        for field in allowed_fields:
            if field in update_data and update_data[field] is not None:
                setattr(subject, field, update_data[field])
        subject.updated_at = BaseRepository.get_current_time()
        db.session.commit()
        return subject

    @staticmethod
    def soft_delete(subject_id: str):
        subject = SubjectRepository.get_by_id(subject_id)
        if not subject:
            return False
        now = BaseRepository.get_current_time()
        subject.deleted_at = now
        subject.updated_at = now
        Enrollment.query.filter_by(subject_id=subject_id, deleted_at=None).update(
            {"deleted_at": now, "updated_at": now}, synchronize_session=False
        )
        db.session.commit()
        return True

    @staticmethod
    def get_enrolled_students(subject_id: str, limit: int = 50, offset: int = 0, q: str = None):
        query = (
            db.session.query(Student, Enrollment)
            .join(Enrollment, (Enrollment.student_id == Student.student_id) & (Enrollment.deleted_at.is_(None)))
            .filter(Enrollment.subject_id == subject_id)
            .filter(Student.deleted_at.is_(None))
        )
        if q and q.strip():
            kw = f"%{q.strip()}%"
            query = query.filter(
                sa.or_(
                    Student.student_id.ilike(kw),
                    Student.full_name.ilike(kw),
                    Student.email.ilike(kw),
                    Student.phone.ilike(kw),
                )
            )
        total = query.count()
        rows = query.order_by(Student.student_id.asc()).offset(offset).limit(limit).all()
        items = []
        for student, enrollment in rows:
            s_dict = student.to_dict()
            s_dict["enrollment_status"] = enrollment.enrollment_status
            s_dict["enrollment_uuid"] = enrollment.uuid
            items.append(s_dict)
        return items, total

    @staticmethod
    def enroll_student(subject_id: str, student_id: str, enrollment_status: str = "Enrolled"):
        student = Student.query.filter_by(student_id=student_id, deleted_at=None).first()
        if not student:
            raise KeyError(f"Không tìm thấy sinh viên với mã '{student_id}'.")
        subject = SubjectRepository.get_by_id(subject_id)
        if not subject:
            raise KeyError(f"Không tìm thấy môn học với mã '{subject_id}'.")

        now = BaseRepository.get_current_time()
        existing = Enrollment.query.filter_by(subject_id=subject_id, student_id=student_id).first()
        if existing:
            if existing.deleted_at is not None:
                existing.deleted_at = None
                existing.enrollment_status = enrollment_status or "Enrolled"
                existing.updated_at = now
                db.session.commit()
                return existing, False
            if enrollment_status and existing.enrollment_status != enrollment_status:
                existing.enrollment_status = enrollment_status
                existing.updated_at = now
                db.session.commit()
            return existing, True

        new_enr = Enrollment(
            student_id=student_id,
            subject_id=subject_id,
            enrollment_status=enrollment_status or "Enrolled",
            uuid=BaseRepository.generate_uuid(),
            updated_at=now,
        )
        db.session.add(new_enr)
        db.session.commit()
        return new_enr, False

    @staticmethod
    def unenroll_student(subject_id: str, student_id: str):
        existing = Enrollment.query.filter_by(
            subject_id=subject_id, student_id=student_id, deleted_at=None
        ).first()
        if not existing:
            return False
        now = BaseRepository.get_current_time()
        existing.deleted_at = now
        existing.updated_at = now
        db.session.commit()
        return True
