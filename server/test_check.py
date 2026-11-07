import os
import sys

# Thêm thư mục hiện tại vào đường dẫn để Python nhận diện package app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.repositories.student_repository import StudentRepository

app = create_app()

with app.app_context():
    print("Đang kiểm tra kết nối PostgreSQL và Repository...")
    try:
        # Tạo bảng nếu chưa có trong DB
        db.create_all()
        print("-> Kết nối DB và tạo bảng thành công!")

        # Kiểm tra truy vấn StudentRepository
        students = StudentRepository.get_all(limit=5)
        print(f"-> Số lượng sinh viên hiện tại: {len(students)}")
    except Exception as e:
        print(f"-> LỖI: Không thể kết nối hoặc thực thi Repository: {e}")