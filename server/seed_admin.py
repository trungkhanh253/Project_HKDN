"""
Script tạo sẵn tài khoản Admin / Super Admin mẫu để test API đăng nhập và đồng bộ.

Cách chạy:
  Trong container:
    docker compose exec api python seed_admin.py
  Hoặc qua Flask CLI:
    docker compose exec api flask --app "app:create_app()" seed-admin
  Hoặc trên máy host (đã cấu hình DATABASE_URL):
    cd server && python seed_admin.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import Admin
from app.auth import hash_password_sha256
from app.repositories.base_repository import BaseRepository

DEFAULT_ADMINS = [
    {
        "admin_id": "SADM_001",
        "uuid": "00000000-0000-4000-8000-000000000001",
        "email": "admin@hkdn.edu.vn",
        "raw_password": "admin123",
        "full_name": "Quản Trị Viên Hệ Thống (Super Admin)",
        "phone": "0901234567",
        "gender": "Nam",
        "role": "SUPER_ADMIN",
        "admin_code": "SADM001",
        "is_first_login": 0,
    },
    {
        "admin_id": "ADM_001",
        "uuid": "00000000-0000-4000-8000-000000000002",
        "email": "lecturer@hkdn.edu.vn",
        "raw_password": "lecturer123",
        "full_name": "Giảng Viên Mẫu",
        "phone": "0909876543",
        "gender": "Nam",
        "role": "ADMIN",
        "admin_code": "GV001",
        "is_first_login": 0,
    },
]


def seed_default_admins():
    now = BaseRepository.get_current_time()
    for item in DEFAULT_ADMINS:
        admin = Admin.query.filter(
            (Admin.admin_id == item["admin_id"]) | (Admin.email == item["email"])
        ).first()
        if not admin:
            admin = Admin(
                admin_id=item["admin_id"],
                uuid=item["uuid"],
                email=item["email"],
                password=hash_password_sha256(item["raw_password"]),
                full_name=item["full_name"],
                phone=item["phone"],
                gender=item["gender"],
                role=item["role"],
                admin_code=item["admin_code"],
                is_first_login=item["is_first_login"],
                updated_at=now,
                deleted_at=None,
            )
            db.session.add(admin)
            print(f"[+] Đã tạo tài khoản: {item['email']} / Mật khẩu: {item['raw_password']} ({item['role']})")
        else:
            admin.password = hash_password_sha256(item["raw_password"])
            admin.full_name = item["full_name"]
            admin.role = item["role"]
            admin.deleted_at = None
            admin.updated_at = now
            print(f"[~] Đã cập nhật tài khoản: {item['email']} / Mật khẩu: {item['raw_password']} ({item['role']})")
    db.session.commit()


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed_default_admins()

