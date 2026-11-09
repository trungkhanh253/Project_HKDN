import csv
import io
from app import create_app, db
from app.models import Admin, Subject, Student, Enrollment
from app.repositories.base_repository import BaseRepository
from app.auth import hash_password_sha256


def process_csv_import(csv_content: str, import_type: str = None, default_subject_id: str = None) -> dict:
    """
    Hàm xử lý import CSV chạy trên RQ Worker (hoặc trực tiếp).
    Hỗ trợ 3 loại dữ liệu:
    - students (mặc định): student_id, full_name, [phone, email, checkin_password, photo_path, subject_id, class_name]
    - subjects: subject_id, subject_name, [time_slot, created_by, instructor_id, subject_status, semester_start_date, semester_end_date]
    - admin: [admin_id], email, full_name, [password, phone, date_of_birth, gender, role, admin_code, description]
    """
    app = create_app()
    with app.app_context():
        if not csv_content or not csv_content.strip():
            raise ValueError("Nội dung file CSV trống.")

        # Loại bỏ UTF-8 BOM nếu có
        if csv_content.startswith("\ufeff"):
            csv_content = csv_content.lstrip("\ufeff")

        reader = csv.DictReader(io.StringIO(csv_content.strip()))
        if not reader.fieldnames:
            raise ValueError("File CSV thiếu dòng tiêu đề (header).")

        headers = [h.strip().lower() for h in reader.fieldnames if h]

        # Tự động nhận diện loại CSV nếu client không truyền trường `type`
        resolved_type = (import_type or "").strip().lower()
        if not resolved_type:
            if "subject_name" in headers:
                resolved_type = "subjects"
            elif "admin_id" in headers or ("email" in headers and "role" in headers and "student_id" not in headers):
                resolved_type = "admin"
            else:
                resolved_type = "students"

        total_rows = 0
        imported = 0
        updated = 0
        skipped = 0
        errors = []
        now = BaseRepository.get_current_time()

        for idx, raw_row in enumerate(reader, start=2):
            row = {
                (k.strip().lower() if k else ""): (v.strip() if isinstance(v, str) else "")
                for k, v in raw_row.items()
                if k is not None
            }
            if not any(row.values()):
                continue

            total_rows += 1
            try:
                if resolved_type in ("student", "students"):
                    student_id = row.get("student_id", "")
                    full_name = row.get("full_name", "")
                    if not student_id or not full_name:
                        skipped += 1
                        errors.append(f"Dòng {idx}: Thiếu student_id hoặc full_name.")
                        continue

                    student = Student.query.filter_by(student_id=student_id).first()
                    is_new = student is None
                    if is_new:
                        student = Student(
                            student_id=student_id,
                            uuid=row.get("uuid") or BaseRepository.generate_uuid(),
                        )
                        db.session.add(student)

                    student.full_name = full_name
                    if row.get("email"):
                        student.email = row["email"]
                    if row.get("phone"):
                        student.phone = row["phone"]
                    if row.get("checkin_password"):
                        student.checkin_password = row["checkin_password"]
                    if "photo_path" in row:
                        photo = row["photo_path"]
                        student.photo_path = None if (not photo or photo.upper() == "NULL") else photo

                    student.updated_at = now
                    student.deleted_at = None
                    db.session.flush()

                    # Nếu có subject_id trong dòng CSV hoặc truyền qua form-data thì tự động ghi danh vào enrollments
                    subj_id = row.get("subject_id") or default_subject_id
                    if subj_id and Subject.query.filter_by(subject_id=subj_id).first():
                        enrollment = Enrollment.query.filter_by(
                            student_id=student_id,
                            subject_id=subj_id,
                        ).first()
                        if not enrollment:
                            enrollment = Enrollment(
                                student_id=student_id,
                                subject_id=subj_id,
                                enrollment_status=row.get("enrollment_status") or "Not Enrolled",
                                uuid=BaseRepository.generate_uuid(),
                                updated_at=now,
                            )
                            db.session.add(enrollment)
                        else:
                            enrollment.deleted_at = None
                            enrollment.updated_at = now

                    if is_new:
                        imported += 1
                    else:
                        updated += 1

                elif resolved_type in ("subject", "subjects"):
                    subject_id = row.get("subject_id") or row.get("subject_code", "")
                    subject_name = row.get("subject_name", "")
                    if not subject_id or not subject_name:
                        skipped += 1
                        errors.append(f"Dòng {idx}: Thiếu subject_id hoặc subject_name.")
                        continue

                    subject = Subject.query.filter_by(subject_id=subject_id).first()
                    is_new = subject is None
                    if is_new:
                        subject = Subject(
                            subject_id=subject_id,
                            uuid=row.get("uuid") or BaseRepository.generate_uuid(),
                        )
                        db.session.add(subject)

                    subject.subject_name = subject_name
                    for field in (
                        "time_slot",
                        "created_by",
                        "instructor_id",
                        "subject_status",
                        "created_at",
                        "semester_start_date",
                        "semester_end_date",
                    ):
                        if row.get(field):
                            setattr(subject, field, row[field])

                    subject.updated_at = now
                    subject.deleted_at = None
                    if is_new:
                        imported += 1
                    else:
                        updated += 1

                elif resolved_type in ("admin", "admins", "lecturer", "lecturers"):
                    email = row.get("email", "")
                    full_name = row.get("full_name", "")
                    admin_id = row.get("admin_id") or (f"ADM_{email.split('@')[0]}" if email else "")
                    if not admin_id or not email or not full_name:
                        skipped += 1
                        errors.append(f"Dòng {idx}: Thiếu admin_id, email hoặc full_name.")
                        continue

                    admin = Admin.query.filter(
                        (Admin.admin_id == admin_id) | (Admin.email == email)
                    ).first()
                    is_new = admin is None
                    if is_new:
                        admin = Admin(
                            admin_id=admin_id,
                            email=email,
                            password=hash_password_sha256(row.get("password") or "123456"),
                            full_name=full_name,
                            uuid=row.get("uuid") or BaseRepository.generate_uuid(),
                        )
                        db.session.add(admin)
                    else:
                        admin.email = email
                        admin.full_name = full_name
                        if row.get("password"):
                            admin.password = hash_password_sha256(row["password"])

                    for field in (
                        "date_of_birth",
                        "phone",
                        "gender",
                        "photo_path",
                        "description",
                        "role",
                        "admin_code",
                    ):
                        if row.get(field):
                            setattr(admin, field, row[field])

                    admin.updated_at = now
                    admin.deleted_at = None
                    if is_new:
                        imported += 1
                    else:
                        updated += 1
                else:
                    raise ValueError(f"Loại import '{resolved_type}' không được hỗ trợ.")

            except Exception as row_exc:
                skipped += 1
                errors.append(f"Dòng {idx}: {str(row_exc)}")

        db.session.commit()
        return {
            "type": resolved_type,
            "total_rows": total_rows,
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

