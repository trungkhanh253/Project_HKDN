from app import db
from app.models import Student, Enrollment, Subject
from app.repositories.base_repository import BaseRepository
import sqlalchemy as sa

class StudentRepository(BaseRepository):
    @staticmethod
    def get_by_id(student_id: str, include_deleted: bool = False):
        query = Student.query.filter_by(student_id=student_id)
        if not include_deleted:
            query = query.filter(Student.deleted_at.is_(None))
        return query.first()

    @staticmethod
    def get_all(limit=100, offset=0):
        return Student.query.filter(Student.deleted_at.is_(None)).offset(offset).limit(limit).all()

    @staticmethod
    def list_paginated(q: str = None, sort: str = None, limit: int = 10, offset: int = 0):
        """
        Tìm kiếm và phân trang sinh viên hỗ trợ:
        - q: tìm kiếm gần đúng theo student_id, full_name, email, phone
        - sort: cột sắp xếp, vd: student_id:asc, full_name:desc, created_at:desc
        """
        query = Student.query.filter(Student.deleted_at.is_(None))

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

        # Xử lý sắp xếp
        if sort:
            parts = sort.split(":")
            field_name = parts[0].strip().lower()
            order_dir = parts[1].strip().lower() if len(parts) > 1 else "asc"

            col = getattr(Student, field_name, None)
            if col is not None:
                query = query.order_by(col.desc() if order_dir == "desc" else col.asc())
            else:
                query = query.order_by(Student.student_id.asc())
        else:
            query = query.order_by(Student.student_id.asc())

        items = query.offset(offset).limit(limit).all()
        return items, total

    @staticmethod
    def create_student(data: dict, subject_id: str = None):
        """
        Tạo mới sinh viên, nếu có subject_id sẽ tự động tạo enrollment ghi danh môn học.
        """
        student_id = data.get("student_id")
        existing = Student.query.filter_by(student_id=student_id).first()
        now = BaseRepository.get_current_time()

        if existing:
            if existing.deleted_at is not None:
                # Phục hồi sinh viên đã bị xóa mềm trước đó
                existing.deleted_at = None
                existing.full_name = data.get("full_name", existing.full_name)
                existing.email = data.get("email", existing.email)
                existing.phone = data.get("phone", existing.phone)
                existing.photo_path = data.get("photo_path", existing.photo_path)
                existing.checkin_password = data.get("checkin_password", existing.checkin_password)
                existing.face_embedding = data.get("face_embedding", existing.face_embedding)
                existing.updated_at = now
                student = existing
            else:
                raise ValueError(f"Sinh viên với mã '{student_id}' đã tồn tại trong hệ thống.")
        else:
            student = Student(
                student_id=student_id,
                full_name=data.get("full_name"),
                email=data.get("email"),
                phone=data.get("phone"),
                photo_path=data.get("photo_path"),
                checkin_password=data.get("checkin_password"),
                face_embedding=data.get("face_embedding"),
                uuid=data.get("uuid", BaseRepository.generate_uuid()),
                updated_at=now,
            )
            db.session.add(student)

        db.session.flush()

        # Tự động ghi danh vào môn học nếu có subject_id
        if subject_id:
            subj = Subject.query.filter_by(subject_id=subject_id, deleted_at=None).first()
            if not subj:
                raise ValueError(f"Môn học với mã '{subject_id}' không tồn tại.")

            enr = Enrollment.query.filter_by(student_id=student_id, subject_id=subject_id).first()
            if not enr:
                enr = Enrollment(
                    student_id=student_id,
                    subject_id=subject_id,
                    enrollment_status="ACTIVE",
                    uuid=BaseRepository.generate_uuid(),
                    updated_at=now,
                )
                db.session.add(enr)
            else:
                enr.deleted_at = None
                enr.updated_at = now

        db.session.commit()
        return student

    @staticmethod
    def update_student(student_id: str, data: dict):
        student = Student.query.filter_by(student_id=student_id, deleted_at=None).first()
        if not student:
            return None

        now = BaseRepository.get_current_time()
        for field in ("full_name", "email", "phone", "photo_path", "checkin_password", "face_embedding"):
            if field in data:
                setattr(student, field, data[field])

        student.updated_at = now
        db.session.commit()
        return student

    @staticmethod
    def soft_delete_student(student_id: str):
        """
        Xóa mềm sinh viên: cập nhật deleted_at để trigger bump_sync_metadata tự tăng seq.
        """
        student = Student.query.filter_by(student_id=student_id, deleted_at=None).first()
        if not student:
            return None

        now = BaseRepository.get_current_time()
        student.deleted_at = now
        student.updated_at = now

        # Đồng thời xóa mềm các bản ghi enrollment liên quan
        enrollments = Enrollment.query.filter_by(student_id=student_id, deleted_at=None).all()
        for enr in enrollments:
            enr.deleted_at = now
            enr.updated_at = now

        db.session.commit()
        return student

    @staticmethod
    def create_or_update(student_data: dict):
        student = Student.query.filter_by(student_id=student_data.get('student_id')).first()
        now = BaseRepository.get_current_time()
        
        if not student:
            student = Student(
                student_id=student_data['student_id'],
                uuid=student_data.get('uuid', BaseRepository.generate_uuid())
            )
            db.session.add(student)

        student.full_name = student_data.get('full_name', student.full_name)
        student.email = student_data.get('email', student.email)
        student.phone = student_data.get('phone', student.phone)
        student.photo_path = student_data.get('photo_path', student.photo_path)
        student.checkin_password = student_data.get('checkin_password', student.checkin_password)
        student.face_embedding = student_data.get('face_embedding', student.face_embedding)
        student.updated_at = now
        student.deleted_at = None

        db.session.commit()
        return student

    @staticmethod
    def find_nearest_face(target_embedding: list, threshold: float = 0.4):
        if not isinstance(target_embedding, (list, tuple)) or len(target_embedding) != 192:
            raise ValueError("Vector khuôn mặt (target_embedding) phải có đúng 192 chiều.")

        distance_col = Student.face_embedding.cosine_distance(target_embedding).label("distance")
        result = (
            db.session.query(Student, distance_col)
            .filter(
                Student.deleted_at.is_(None),
                Student.face_embedding.isnot(None),
            )
            .order_by(distance_col.asc())
            .first()
        )

        if result and result.distance is not None and float(result.distance) <= threshold:
            return result.Student, float(result.distance)
        return None, None
