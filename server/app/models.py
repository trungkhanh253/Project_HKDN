from datetime import datetime
from pgvector.sqlalchemy import Vector
from app import db

class SequenceMixin:
    seq = db.Column(db.BigInteger, primary_key=False, autoincrement=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

class Admin(db.Model, SequenceMixin):
    __tablename__ = 'admin'
    
    id = db.Column(db.String(50), primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=True)

class Student(db.Model, SequenceMixin):
    __tablename__ = 'student'
    
    student_id = db.Column(db.String(20), primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    class_name = db.Column(db.String(50), nullable=False)
    face_embedding = db.Column(Vector(192), nullable=True)

class Subject(db.Model, SequenceMixin):
    __tablename__ = 'subject'
    
    subject_code = db.Column(db.String(20), primary_key=True)
    subject_name = db.Column(db.String(100), nullable=False)
    credits = db.Column(db.Integer, nullable=False, default=3)

class Enrollment(db.Model, SequenceMixin):
    __tablename__ = 'enrollment'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(20), db.ForeignKey('student.student_id'), nullable=False)
    subject_code = db.Column(db.String(20), db.ForeignKey('subject.subject_code'), nullable=False)

class CheckinHistory(db.Model, SequenceMixin):
    __tablename__ = 'checkin_history'
    
    id = db.Column(db.String(50), primary_key=True)
    student_id = db.Column(db.String(20), db.ForeignKey('student.student_id'), nullable=False)
    subject_code = db.Column(db.String(20), db.ForeignKey('subject.subject_code'), nullable=False)
    checkin_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='PRESENT')

class EmailRecipient(db.Model, SequenceMixin):
    __tablename__ = 'email_recipient'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), nullable=False)