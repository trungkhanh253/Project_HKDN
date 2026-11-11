from app import db
from app.models import Student
from app.repositories.base_repository import BaseRepository

class StudentRepository(BaseRepository):
    @staticmethod
    def get_by_id(student_id: str):
        return Student.query.filter_by(student_id=student_id, deleted_at=None).first()

    @staticmethod
    def get_all(limit=100, offset=0):
        return Student.query.filter_by(deleted_at=None).offset(offset).limit(limit).all()

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
        """
        Tìm kiếm khuôn mặt gần nhất trong DB bằng Cosine Distance qua pgvector (192 chiều).
        Trả về (student, distance) nếu khoảng cách <= threshold, ngược lại trả về (None, None).
        """
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
