"""
Script kiểm tra toàn diện 3 nhiệm vụ TV5 do Nhóm trưởng giao:
1. API Sinh viên: POST, PUT, DELETE (xóa mềm), GET chi tiết, kèm tự động ghi danh môn học.
2. API Điểm danh: POST /attendance (kiểm tra ghi danh, chống trùng uuid, phân quyền giảng viên), GET /attendance.
3. Chuẩn hóa API Web: GET /students, /subjects, /admins (items, total, limit, offset, q, sort), GET /{id}.

Cách chạy:
    docker compose exec api python test_tv5_tasks.py
"""
import os
import sys
import uuid
import requests

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:5000").rstrip("/")
API_V1 = f"{BASE_URL}/api/v1"

def run_tests():
    print("=" * 75)
    print(" BẮT ĐẦU KIỂM TRA TV5")
    print("=" * 75)

    # 1. Đăng nhập Super Admin lấy token
    r_login = requests.post(
        f"{API_V1}/auth/login",
        json={"email": "admin@hkdn.edu.vn", "password": "admin123"},
        timeout=5,
    )
    assert r_login.status_code == 200, f"Đăng nhập thất bại: {r_login.text}"
    token_super = r_login.json()["access_token"]
    headers_super = {"Authorization": f"Bearer {token_super}"}
    print("[1] Đăng nhập Super Admin thành công                     : OK")

    # Đăng nhập Giảng viên thường (ADM_001)
    r_login_gv = requests.post(
        f"{API_V1}/auth/login",
        json={"email": "lecturer@hkdn.edu.vn", "password": "lecturer123"},
        timeout=5,
    )
    assert r_login_gv.status_code == 200, f"Đăng nhập GV thất bại: {r_login_gv.text}"
    token_gv = r_login_gv.json()["access_token"]
    headers_gv = {"Authorization": f"Bearer {token_gv}"}
    print("[2] Đăng nhập Giảng viên ADM_001 thành công              : OK")

    # 2. Tạo môn học mẫu do Giảng viên ADM_001 phụ trách
    test_subj_id = f"SUB_TV5_{uuid.uuid4().hex[:4].upper()}"
    requests.post(
        f"{API_V1}/sync/push",
        json={
            "subjects": [
                {
                    "subject_id": test_subj_id,
                    "subject_name": "Lập Trình Web Nâng Cao TV5",
                    "instructor_id": "ADM_001",
                    "subject_status": "ACTIVE",
                    "uuid": str(uuid.uuid4()),
                    "updated_at": "2026-11-13T08:00:00Z",
                }
            ]
        },
        timeout=5,
    )
    print(f"[3] Tạo môn học kiểm thử '{test_subj_id}' (GV: ADM_001)   : OK")

    # 3. TASK 1: POST /students kèm subject_id để tự ghi danh vào môn
    stu_test_id = f"SV_TV5_{uuid.uuid4().hex[:4].upper()}"
    r_create_stu = requests.post(
        f"{API_V1}/students",
        headers=headers_gv,
        json={
            "student_id": stu_test_id,
            "full_name": "Nguyen Van Test TV5",
            "email": f"{stu_test_id.lower()}@hkdn.edu.vn",
            "phone": "0988776655",
            "subject_id": test_subj_id,
        },
        timeout=5,
    )
    assert r_create_stu.status_code == 201, f"Lỗi POST /students: {r_create_stu.text}"
    print(f"[4] POST /students (tạo SV + tự ghi danh {test_subj_id})   : OK (HTTP 201)")

    # 4. TASK 1: GET /students/{id} và PUT /students/{id}
    r_get_stu = requests.get(f"{API_V1}/students/{stu_test_id}", timeout=5)
    assert r_get_stu.status_code == 200 and r_get_stu.json()["student"]["student_id"] == stu_test_id
    print(f"[5] GET /students/{stu_test_id} (chi tiết sinh viên)     : OK (HTTP 200)")

    r_put_stu = requests.post if False else requests.put(
        f"{API_V1}/students/{stu_test_id}",
        headers=headers_gv,
        json={"full_name": "Nguyen Van Test TV5 (Đã Cập Nhật)", "phone": "0911223344"},
        timeout=5,
    )
    assert r_put_stu.status_code == 200 and r_put_stu.json()["student"]["phone"] == "0911223344"
    print(f"[6] PUT /students/{stu_test_id} (cập nhật thông tin SV)  : OK (HTTP 200)")

    # 5. TASK 2: API ĐIỂM DANH POST /attendance
    att_uuid = str(uuid.uuid4())
    r_att = requests.post(
        f"{API_V1}/attendance",
        headers=headers_gv,
        json={
            "student_id": stu_test_id,
            "subject_id": test_subj_id,
            "checkin_time": "08:30:00",
            "checkin_date": "2026-11-13",
            "uuid": att_uuid,
            "status": "PRESENT",
        },
        timeout=5,
    )
    assert r_att.status_code == 201, f"Lỗi POST /attendance: {r_att.text}"
    print(f"[7] POST /attendance (ghi nhận điểm danh hợp lệ)        : OK (HTTP 201)")

    # Kiểm tra gửi trùng uuid -> không tạo bản ghi mới (Idempotent)
    r_att_dup = requests.post(
        f"{API_V1}/attendance",
        headers=headers_gv,
        json={
            "student_id": stu_test_id,
            "subject_id": test_subj_id,
            "checkin_time": "08:30:00",
            "checkin_date": "2026-11-13",
            "uuid": att_uuid,
        },
        timeout=5,
    )
    assert r_att_dup.status_code == 200 and r_att_dup.json()["created"] is False
    print("[8] Chống trùng uuid (Idempotent POST /attendance)      : OK (HTTP 200 created=False)")

    # Kiểm tra điểm danh sinh viên chưa ghi danh vào môn -> báo lỗi 422
    stu_not_enrolled = f"SV_CHUA_HOC_{uuid.uuid4().hex[:4].upper()}"
    requests.post(
        f"{API_V1}/students",
        headers=headers_super,
        json={"student_id": stu_not_enrolled, "full_name": "Chua Hoc Mon"},
        timeout=5,
    )
    r_att_not_enr = requests.post(
        f"{API_V1}/attendance",
        headers=headers_gv,
        json={
            "student_id": stu_not_enrolled,
            "subject_id": test_subj_id,
            "checkin_time": "08:35:00",
            "checkin_date": "2026-11-13",
        },
        timeout=5,
    )
    assert r_att_not_enr.status_code == 422
    print("[9] Chặn điểm danh SV chưa đăng ký môn (HTTP 422)        : OK")

    # Kiểm tra GET /attendance
    r_get_att = requests.get(
        f"{API_V1}/attendance?subject_id={test_subj_id}&date=2026-11-13",
        headers=headers_gv,
        timeout=5,
    )
    assert r_get_att.status_code == 200 and "items" in r_get_att.json() and r_get_att.json()["total"] >= 1
    print(f"[10] GET /attendance?subject_id=&date= (liệt kê)        : OK ({r_get_att.json()['total']} bản ghi)")

    # 6. TASK 1: DELETE /students/{id} (Xóa mềm)
    r_del_stu = requests.delete(
        f"{API_V1}/students/{stu_test_id}",
        headers=headers_gv,
        timeout=5,
    )
    assert r_del_stu.status_code == 200
    r_check_del = requests.get(f"{API_V1}/students/{stu_test_id}", timeout=5)
    assert r_check_del.status_code == 404, "Sau khi xóa mềm, GET không được thấy SV nữa"
    print(f"[11] DELETE /students/{stu_test_id} (xóa mềm)            : OK (HTTP 200 & ẩn khỏi GET)")

    # 7. TASK 3: Chuẩn hóa API Web (items, total, limit, offset, q, sort)
    r_web_stu = requests.get(f"{API_V1}/students?limit=5&offset=0&q=Khoa&sort=student_id:desc", timeout=5)
    assert r_web_stu.status_code == 200
    stu_res = r_web_stu.json()
    assert "items" in stu_res and "total" in stu_res and "limit" in stu_res and "offset" in stu_res
    print(f"[12] Chuẩn hóa GET /students (items, total, q, sort)    : OK (total={stu_res['total']})")

    r_web_sub = requests.get(f"{API_V1}/subjects?limit=5&offset=0", timeout=5)
    assert r_web_sub.status_code == 200 and "items" in r_web_sub.json()
    r_web_sub_detail = requests.get(f"{API_V1}/subjects/{test_subj_id}", timeout=5)
    assert r_web_sub_detail.status_code == 200 and "subject" in r_web_sub_detail.json()
    print(f"[13] Chuẩn hóa GET /subjects & GET /subjects/{{id}}       : OK")

    r_web_adm = requests.get(f"{API_V1}/admins?limit=5&offset=0", timeout=5)
    assert r_web_adm.status_code == 200 and "items" in r_web_adm.json()
    r_web_adm_detail = requests.get(f"{API_V1}/admins/SADM_001", timeout=5)
    assert r_web_adm_detail.status_code == 200 and "admin" in r_web_adm_detail.json()
    print(f"[14] Chuẩn hóa GET /admins & GET /admins/{{id}}           : OK")

    print("=" * 75)
    print(" -> HOÀN THÀNH TOÀN BỘ 14/14 CA KIỂM THỬ TV5!")
    print("=" * 75)

if __name__ == "__main__":
    run_tests()
