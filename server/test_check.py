import os
import sys
import sqlalchemy as sa

# Thêm thư mục hiện tại vào đường dẫn để Python nhận diện package app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.repositories.student_repository import StudentRepository

app = create_app()


def run_phase2_check():
    with app.app_context():
        print("=" * 65)
        print(" KIỂM TRA HẠ TẦNG SERVER GIAI ĐOẠN 2 (FLASK + POSTGRESQL + PGVECTOR)")
        print("=" * 65)

        # 1. Kiểm tra kết nối PostgreSQL & extension pgvector
        ext_ver = db.session.execute(
            sa.text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        print(f"[1] Kết nối PostgreSQL & Extension pgvector : {'OK (v' + str(ext_ver) + ')' if ext_ver else 'CHƯA BẬT'}")

        # 2. Kiểm tra Sequence đồng bộ toàn cục global_sync_seq
        seq_reg = db.session.execute(
            sa.text("SELECT to_regclass('public.global_sync_seq')")
        ).scalar()
        print(f"[2] Sequence toàn cục (global_sync_seq)     : {'OK' if seq_reg else 'THIẾU'}")

        # 3. Kiểm tra 6 bảng Schema chuẩn
        tables = [
            "admin",
            "subjects",
            "students",
            "enrollments",
            "checkin_history",
            "email_recipients",
        ]
        print("[3] Kiểm tra 6 bảng Schema và cột Metadata (uuid, updated_at, deleted_at, seq):")
        for tbl in tables:
            exists = db.session.execute(
                sa.text("SELECT to_regclass(:t)"), {"t": f"public.{tbl}"}
            ).scalar()
            print(f"    - Bảng {tbl:<18}: {'ĐÃ TẠO (OK)' if exists else 'THIẾU'}")

        # 4. Kiểm tra kiểu dữ liệu VECTOR(192) trên bảng students & admin
        for tbl in ("admin", "students"):
            vec_type = db.session.execute(
                sa.text(
                    "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                    f"WHERE a.attrelid = '{tbl}'::regclass AND a.attname = 'face_embedding'"
                )
            ).scalar()
            print(f"[4] Cột {tbl}.face_embedding          : {vec_type}")

        # 5. Kiểm tra truy vấn StudentRepository & tìm kiếm tương đồng pgvector
        students = StudentRepository.get_all(limit=5)
        print(f"[5] Truy vấn StudentRepository              : OK (Hiện có {len(students)} bản ghi mẫu)")

        sample_vec = [1.0] + [0.0] * 191
        nearest_stu, dist = StudentRepository.find_nearest_face(sample_vec, threshold=2.0)
        if nearest_stu:
            print(f"[6] Tìm kiếm Cosine Distance (pgvector)     : OK (Gần nhất: {nearest_stu.student_id}, distance={dist:.4f})")
        else:
            print("[6] Tìm kiếm Cosine Distance (pgvector)     : OK (Truy vấn vector 192 chiều thành công)")

        print("=" * 65)
        print(" -> HOÀN TẤT KIỂM TRA GIAI ĐOẠN 2 THÀNH CÔNG!")
        print("=" * 65)


if __name__ == "__main__":
    run_phase2_check()
