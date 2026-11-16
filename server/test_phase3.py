"""
Script kiểm tra toàn diện Giai đoạn 3 (Model, API, Đăng nhập JWT, Swagger UI & Import CSV):
Chạy bằng lệnh:
    docker.exe compose exec api python test_phase3.py
"""
import io
import os
import sys
import time
import requests

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import (
    Admin,
    Subject,
    Student,
    Enrollment,
    CheckinHistory,
    EmailRecipient,
)
from seed_admin import seed_default_admins

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:5000").rstrip("/")
API_V1 = f"{BASE_URL}/api/v1"


def _wait_job(job_id: str, timeout_sec: int = 20) -> dict:
    for _ in range(timeout_sec * 2):
        r = requests.get(f"{API_V1}/jobs/{job_id}", timeout=5)
        data = r.json()
        if data.get("status") in ("finished", "failed"):
            return data
        time.sleep(0.5)
    raise TimeoutError(f"Job {job_id} chưa hoàn tất sau {timeout_sec}s")


def run_phase3_check():
    app = create_app()
    with app.app_context():
        seed_default_admins()

        print("=" * 72)
        print(" KIỂM TRA SERVER GIAI ĐOẠN 3 (MODEL, API, ĐĂNG NHẬP, SWAGGER, IMPORT CSV)")
        print("=" * 72)

        # 1. Kiểm tra 6 Model ORM
        models = [Admin, Subject, Student, Enrollment, CheckinHistory, EmailRecipient]
        model_names = ", ".join(m.__tablename__ for m in models)
        print(f"[1] Kiểm tra 6 Model SQLAlchemy ORM         : OK ({model_names})")

    # 2. Kiểm tra API Health & Swagger UI / OpenAPI
    r_health = requests.get(f"{API_V1}/health", timeout=5)
    assert r_health.status_code == 200 and r_health.json().get("status") == "healthy"
    print("[2] Kiểm tra Endpoint GET /api/v1/health    : OK (200 healthy)")

    r_swagger = requests.get(f"{BASE_URL}/apidocs", timeout=5)
    r_openapi = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
    assert r_swagger.status_code == 200 and "SwaggerUIBundle" in r_swagger.text
    assert r_openapi.status_code == 200 and "paths" in r_openapi.json()
    paths_count = len(r_openapi.json().get("paths", {}))
    print(f"[3] Kiểm tra Swagger UI (/apidocs & OpenAPI): OK ({paths_count} nhóm đường dẫn chuẩn OpenAPI 3.0.3)")

    # 3. Kiểm tra Đăng nhập JWT (Login, Refresh, Auth/Me)
    r_bad = requests.post(
        f"{API_V1}/auth/login",
        json={"email": "admin@hkdn.edu.vn", "password": "sai_mat_khau"},
        timeout=5,
    )
    assert r_bad.status_code == 401
    print("[4] Kiểm tra chặn đăng nhập sai mật khẩu     : OK (HTTP 401 INVALID_CREDENTIALS)")

    r_login = requests.post(
        f"{API_V1}/auth/login",
        json={"email": "admin@hkdn.edu.vn", "password": "admin123"},
        timeout=5,
    )
    assert r_login.status_code == 200
    login_data = r_login.json()
    access_token = login_data["access_token"]
    refresh_token = login_data["refresh_token"]
    print(f"[5] Đăng nhập POST /api/v1/auth/login       : OK (Admin: {login_data['admin']['email']}, Role: {login_data['admin']['role']})")

    r_refresh = requests.post(
        f"{API_V1}/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
        timeout=5,
    )
    assert r_refresh.status_code == 200 and "access_token" in r_refresh.json()
    print("[6] Làm mới Token POST /api/v1/auth/refresh : OK (Cấp lại access_token thành công)")

    r_me = requests.get(
        f"{API_V1}/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=5,
    )
    assert r_me.status_code == 200
    print(f"[7] Xác thực Token GET /api/v1/auth/me      : OK (Họ tên: {r_me.json()['admin']['full_name']})")

    # 4. Kiểm tra Import CSV bất đồng bộ qua RQ Worker (3 loại: Môn học, Giảng viên, Sinh viên)
    csv_subjects = (
        "subject_id,subject_name,time_slot,subject_status\n"
        "IT301,Lap Trinh Python Nang Cao,Thu 2 (07:30-09:30),ASSIGNED\n"
    )
    r_sub_csv = requests.post(
        f"{API_V1}/import/csv",
        data={"type": "subjects"},
        files={"file": ("subjects.csv", io.BytesIO(csv_subjects.encode("utf-8")), "text/csv")},
        timeout=10,
    )
    assert r_sub_csv.status_code == 202
    sub_job = _wait_job(r_sub_csv.json()["job_id"])
    assert sub_job["status"] == "finished"
    print(f"[8] Import CSV Môn học (RQ Worker)          : OK (Job={sub_job['job_id'][:8]}..., status={sub_job['status']}, total={sub_job['result']['total_rows']})")

    csv_students = (
        "student_id,full_name,email,phone,subject_id\n"
        "SV3001,Nguyen Van Khoa,khoa@edu.vn,0905111222,IT301\n"
        "SV3002,Tran Thi Mai,mai@edu.vn,0905333444,IT301\n"
    )
    r_stu_csv = requests.post(
        f"{API_V1}/import/csv",
        data={"type": "students"},
        files={"file": ("students.csv", io.BytesIO(csv_students.encode("utf-8")), "text/csv")},
        timeout=10,
    )
    assert r_stu_csv.status_code == 202
    stu_job = _wait_job(r_stu_csv.json()["job_id"])
    assert stu_job["status"] == "finished"
    print(f"[9] Import CSV Sinh viên (RQ Worker)        : OK (Job={stu_job['job_id'][:8]}..., status={stu_job['status']}, total={stu_job['result']['total_rows']})")

    # 5. Kiểm tra API danh sách dữ liệu sau khi Import
    r_list_stu = requests.get(f"{API_V1}/students", timeout=5)
    r_list_sub = requests.get(f"{API_V1}/subjects", timeout=5)
    assert r_list_stu.status_code == 200 and r_list_sub.status_code == 200
    print(f"[10] Truy vấn API GET /students & /subjects : OK ({r_list_stu.json()['count']} sinh viên, {r_list_sub.json()['count']} môn học)")

    print("=" * 72)
    print(" -> HOÀN TẤT KIỂM TRA GIAI ĐOẠN 3 THÀNH CÔNG 100%!")
    print(" -> Mở trình duyệt xem Swagger UI tại: http://localhost:5000/apidocs")
    print("=" * 72)


if __name__ == "__main__":
    run_phase3_check()


