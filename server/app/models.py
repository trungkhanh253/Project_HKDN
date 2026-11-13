import uuid as uuid_lib
from datetime import datetime
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from app import db

global_sync_seq = db.Sequence("global_sync_seq", start=1)


def _format_dt(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(dt)


def _format_embedding(emb):
    if emb is None:
        return None
    if hasattr(emb, "tolist"):
        return [float(x) for x in emb.tolist()]
    return [float(x) for x in emb]


class SyncMetadataMixin:
    uuid = db.Column(
        db.String(255),
        unique=True,
        nullable=False,
        default=lambda: str(uuid_lib.uuid4()),
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    deleted_at = db.Column(db.DateTime, nullable=True)
    seq = db.Column(
        db.BigInteger,
        global_sync_seq,
        unique=True,
        nullable=False,
        index=True,
        server_default=sa.text("nextval('global_sync_seq')"),
    )


class Admin(db.Model, SyncMetadataMixin):
    __tablename__ = "admin"

    admin_id = db.Column(db.String(255), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    date_of_birth = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    gender = db.Column(db.String(50), nullable=True)
    photo_path = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    role = db.Column(db.String(50), nullable=False, default="ADMIN", server_default="ADMIN")
    admin_code = db.Column(db.String(100), nullable=True)
    reset_token = db.Column(db.String(255), nullable=True)
    expire_at = db.Column(db.BigInteger, nullable=True)
    is_first_login = db.Column(db.Integer, default=1, server_default="1")
    has_iris = db.Column(db.Integer, default=0, server_default="0")
    face_embedding = db.Column(Vector(192), nullable=True)

    def to_dict(self, include_password=False, include_sensitive=False):
        data = {
            "admin_id": self.admin_id,
            "email": self.email,
            "full_name": self.full_name,
            "date_of_birth": self.date_of_birth,
            "phone": self.phone,
            "gender": self.gender,
            "photo_path": self.photo_path,
            "description": self.description,
            "role": self.role,
            "admin_code": self.admin_code,
            "is_first_login": self.is_first_login,
            "has_iris": self.has_iris,
            "uuid": self.uuid,
            "updated_at": _format_dt(self.updated_at),
            "deleted_at": _format_dt(self.deleted_at),
            "seq": self.seq,
        }

        if include_sensitive:
            data["face_embedding"] = _format_embedding(
                self.face_embedding
            )

        if include_password:
            data["password"] = self.password

        return data


class Subject(db.Model, SyncMetadataMixin):
    __tablename__ = "subjects"

    subject_id = db.Column(db.String(255), primary_key=True)
    subject_name = db.Column(db.String(255), nullable=False)
    time_slot = db.Column(db.String(255), nullable=True)
    created_by = db.Column(
        db.String(255),
        db.ForeignKey("admin.admin_id", ondelete="SET NULL"),
        nullable=True,
    )
    instructor_id = db.Column(
        db.String(255),
        db.ForeignKey("admin.admin_id", ondelete="SET NULL"),
        nullable=True,
    )
    subject_status = db.Column(
        db.String(50),
        nullable=False,
        default="UNASSIGNED",
        server_default="UNASSIGNED",
    )
    created_at = db.Column(db.String(50), nullable=True)
    semester_start_date = db.Column(db.String(50), nullable=True)
    semester_end_date = db.Column(db.String(50), nullable=True)

    def to_dict(self):
        return {
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "time_slot": self.time_slot,
            "created_by": self.created_by,
            "instructor_id": self.instructor_id,
            "subject_status": self.subject_status,
            "created_at": self.created_at,
            "semester_start_date": self.semester_start_date,
            "semester_end_date": self.semester_end_date,
            "uuid": self.uuid,
            "updated_at": _format_dt(self.updated_at),
            "deleted_at": _format_dt(self.deleted_at),
            "seq": self.seq,
        }


class Student(db.Model, SyncMetadataMixin):
    __tablename__ = "students"

    student_id = db.Column(db.String(255), primary_key=True)
    full_name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    photo_path = db.Column(db.Text, nullable=True)
    checkin_password = db.Column(db.String(255), nullable=True)
    face_embedding = db.Column(Vector(192), nullable=True)

    def to_dict(self):
        return {
            "student_id": self.student_id,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "photo_path": self.photo_path,
            "checkin_password": self.checkin_password,
            "face_embedding": _format_embedding(self.face_embedding),
            "uuid": self.uuid,
            "updated_at": _format_dt(self.updated_at),
            "deleted_at": _format_dt(self.deleted_at),
            "seq": self.seq,
        }


class Enrollment(db.Model, SyncMetadataMixin):
    __tablename__ = "enrollments"

    student_id = db.Column(
        db.String(255),
        db.ForeignKey("students.student_id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject_id = db.Column(
        db.String(255),
        db.ForeignKey("subjects.subject_id", ondelete="CASCADE"),
        primary_key=True,
    )
    enrollment_status = db.Column(db.String(50), nullable=True)

    def to_dict(self):
        return {
            "student_id": self.student_id,
            "subject_id": self.subject_id,
            "enrollment_status": self.enrollment_status,
            "uuid": self.uuid,
            "updated_at": _format_dt(self.updated_at),
            "deleted_at": _format_dt(self.deleted_at),
            "seq": self.seq,
        }


class CheckinHistory(db.Model, SyncMetadataMixin):
    __tablename__ = "checkin_history"

    checkin_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(
        db.String(255),
        db.ForeignKey("students.student_id", ondelete="CASCADE"),
        nullable=True,
    )
    subject_id = db.Column(
        db.String(255),
        db.ForeignKey("subjects.subject_id", ondelete="CASCADE"),
        nullable=True,
    )
    checkin_time = db.Column(db.String(50), nullable=True)
    checkin_date = db.Column(db.String(50), nullable=True)

    def to_dict(self):
        return {
            "checkin_id": self.checkin_id,
            "student_id": self.student_id,
            "subject_id": self.subject_id,
            "checkin_time": self.checkin_time,
            "checkin_date": self.checkin_date,
            "uuid": self.uuid,
            "updated_at": _format_dt(self.updated_at),
            "deleted_at": _format_dt(self.deleted_at),
            "seq": self.seq,
        }


class EmailRecipient(db.Model, SyncMetadataMixin):
    __tablename__ = "email_recipients"
    __table_args__ = (
        db.UniqueConstraint("subject_id", "email_address", name="unique_subject_email"),
    )

    email_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    subject_id = db.Column(
        db.String(255),
        db.ForeignKey("subjects.subject_id", ondelete="CASCADE"),
        nullable=False,
    )
    email_address = db.Column(db.String(255), nullable=False)
    recipient_name = db.Column(db.String(255), nullable=True)
    added_date = db.Column(db.String(50), nullable=True)
    is_selected = db.Column(db.Boolean, default=True, server_default=sa.text("TRUE"))

    def to_dict(self):
        return {
            "email_id": self.email_id,
            "subject_id": self.subject_id,
            "email_address": self.email_address,
            "recipient_name": self.recipient_name,
            "added_date": self.added_date,
            "is_selected": self.is_selected,
            "uuid": self.uuid,
            "updated_at": _format_dt(self.updated_at),
            "deleted_at": _format_dt(self.deleted_at),
            "seq": self.seq,
        }

