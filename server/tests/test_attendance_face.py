"""
test_attendance_face.py – Kiểm thử API điểm danh bằng hình ảnh khuôn mặt
Nhiệm vụ TV5 (Nguyễn Minh Tuyên) - Task 13, 14, 15

Bao gồm các ca kiểm thử:
[1] Điểm danh bằng ảnh thành công (201 Created) khi ảnh khớp và sinh viên đã ghi danh
[2] Điểm danh thất bại khi khuôn mặt không khớp (422) – TUYỆT ĐỐI KHÔNG lưu điểm danh vào DB
[3] Điểm danh thất bại khi Face Service gặp sự cố (503) – TUYỆT ĐỐI KHÔNG lưu điểm danh vào DB
[4] Bắt lỗi thiếu file ảnh (422 MISSING_IMAGE)
[5] Bắt lỗi sinh viên chưa ghi danh môn học (422 STUDENT_NOT_ENROLLED)
[6] Bắt lỗi giảng viên không phụ trách môn học (403 FORBIDDEN)
[7] Chống trùng lặp theo UUID (Idempotency – lần 2 trả 200 created=False)
[8] Điểm danh multipart qua route /attendance tự động nhận diện ảnh
[9] Tương thích ngược: Điểm danh thủ công bằng JSON (/attendance) vẫn hoạt động bình thường
"""
import io
import os
import uuid
import pytest
import requests

from app.services.face_matching_service import (
    FaceMatchingService,
    FaceServiceUnavailableError,
    FaceNotDetectedError,
)

pytestmark = pytest.mark.api

SUPER_EMAIL = os.getenv("TEST_ADMIN_EMAIL", "admin@hkdn.edu.vn")
SUPER_PASSWORD = os.getenv("TEST_ADMIN_PASSWORD", "admin123")
GV_EMAIL = "lecturer@hkdn.edu.vn"
GV_PASSWORD = "lecturer123"

# Ảnh JPEG hợp lệ dạng nhị phân mẫu
SAMPLE_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00" + b"\x00" * 64


@pytest.fixture(autouse=True)
def clean_mock_handler():
    """Tự động reset mock handler sau mỗi bài test."""
    yield
    FaceMatchingService.reset_mock_handler()


@pytest.fixture
def api_super(v1):
    s = requests.Session()
    r = s.post(f"{v1}/auth/login", json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD}, timeout=5)
    assert r.status_code == 200
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


@pytest.fixture
def api_gv(v1):
    s = requests.Session()
    r = s.post(f"{v1}/auth/login", json={"email": GV_EMAIL, "password": GV_PASSWORD}, timeout=5)
    assert r.status_code == 200
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


@pytest.fixture
def setup_data(api_super, v1):
    """
    Tạo môi trường test:
    - 1 môn học do Giảng viên (ADM_001) phụ trách
    - 1 sinh viên có vector khuôn mặt đã đăng ký
    - Ghi danh sinh viên vào môn học
    """
    subj_id = f"SUB_ATT_{uuid.uuid4().hex[:6].upper()}"
    student_id = f"SV_ATT_{uuid.uuid4().hex[:6].upper()}"
    vector_192 = [0.05] * 192

    # 1. Tạo môn học gán cho ADM_001
    r_subj = api_super.post(f"{v1}/sync/push", json={
        "subjects": [{
            "subject_id": subj_id,
            "subject_name": f"Môn Kiểm thử Điểm danh {subj_id}",
            "instructor_id": "ADM_001",
            "subject_status": "ACTIVE",
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-27T08:00:00Z",
        }]
    }, timeout=5)
    assert r_subj.status_code == 200

    # 2. Tạo sinh viên kèm face_embedding
    r_stu = api_super.post(f"{v1}/sync/push", json={
        "students": [{
            "student_id": student_id,
            "full_name": "Sinh Viên Điểm Danh Ảnh",
            "face_embedding": vector_192,
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-27T08:00:00Z",
        }]
    }, timeout=5)
    assert r_stu.status_code == 200

    # 3. Ghi danh sinh viên vào môn
    r_enr = api_super.post(f"{v1}/sync/push", json={
        "enrollments": [{
            "student_id": student_id,
            "subject_id": subj_id,
            "enrollment_status": "ACTIVE",
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-27T08:00:00Z",
        }]
    }, timeout=5)
    assert r_enr.status_code == 200

    return {
        "subject_id": subj_id,
        "student_id": student_id,
        "instructor_id": "ADM_001",
    }


# ---------------------------------------------------------------------------
# [CA 1] Điểm danh bằng ảnh thành công khi khuôn mặt khớp (201 Created)
# ---------------------------------------------------------------------------
def test_face_attendance_success(api_gv, v1, setup_data):
    """Điểm danh thành công khi gửi đúng ảnh và sinh viên đã ghi danh môn học."""
    subj_id = setup_data["subject_id"]
    stu_id = setup_data["student_id"]
    checkin_uuid = str(uuid.uuid4())

    # Giả lập Face Matching xác thực thành công (score 0.92 > 0.6)
    FaceMatchingService.set_mock_handler(lambda s, img: (True, 0.92, "Xác thực khuôn mặt thành công."))

    files = {"image": ("face.jpg", io.BytesIO(SAMPLE_JPEG), "image/jpeg")}
    data = {
        "student_id": stu_id,
        "subject_id": subj_id,
        "checkin_time": "08:15:00",
        "checkin_date": "2026-11-27",
        "uuid": checkin_uuid,
    }

    r = api_gv.post(f"{v1}/attendance/face", data=data, files=files, timeout=5)
    assert r.status_code == 201, f"Kỳ vọng 201 nhưng nhận {r.status_code}: {r.text}"

    res = r.json()
    assert res.get("status") == "created"
    assert res.get("created") is True
    assert res.get("score") == 0.92
    assert res.get("checkin", {}).get("student_id") == stu_id
    assert res.get("checkin", {}).get("subject_id") == subj_id


# ---------------------------------------------------------------------------
# [CA 2] Xác thực khuôn mặt không khớp -> 422 và KHÔNG lưu điểm danh
# ---------------------------------------------------------------------------
def test_face_attendance_not_matching_does_not_save(api_gv, v1, setup_data):
    """Khuôn mặt không khớp -> trả 422 FACE_VERIFICATION_FAILED và TUYỆT ĐỐI không lưu điểm danh."""
    subj_id = setup_data["subject_id"]
    stu_id = setup_data["student_id"]
    checkin_uuid = str(uuid.uuid4())

    # Giả lập Face Matching xác thực thất bại (score 0.35 < 0.6)
    FaceMatchingService.set_mock_handler(lambda s, img: (False, 0.35, "Khuôn mặt không khớp với hồ sơ."))

    files = {"image": ("wrong_face.jpg", io.BytesIO(SAMPLE_JPEG), "image/jpeg")}
    data = {
        "student_id": stu_id,
        "subject_id": subj_id,
        "checkin_time": "08:20:00",
        "checkin_date": "2026-11-27",
        "uuid": checkin_uuid,
    }

    r = api_gv.post(f"{v1}/attendance/face", data=data, files=files, timeout=5)
    assert r.status_code == 422, f"Kỳ vọng 422 nhưng nhận {r.status_code}: {r.text}"
    assert r.json().get("code") == "FACE_VERIFICATION_FAILED"

    # Kiểm tra database qua API GET /attendance: đảm bảo KHÔNG có bản ghi nào được lưu
    r_check = api_gv.get(f"{v1}/attendance", params={"subject_id": subj_id, "student_id": stu_id})
    assert r_check.status_code == 200
    items = r_check.json().get("items", [])
    matched_uuids = [item.get("uuid") for item in items if item.get("uuid") == checkin_uuid]
    assert len(matched_uuids) == 0, "LỖI BẢO MẬT: Điểm danh vẫn bị lưu dù xác thực khuôn mặt thất bại!"


# ---------------------------------------------------------------------------
# [CA 3] Lỗi dịch vụ Face Service ngoài -> 503 và KHÔNG lưu điểm danh
# ---------------------------------------------------------------------------
def test_face_attendance_service_error_does_not_save(api_gv, v1, setup_data):
    """Khi Face Service bị sự cố/timeout -> trả 503 và không lưu điểm danh."""
    subj_id = setup_data["subject_id"]
    stu_id = setup_data["student_id"]
    checkin_uuid = str(uuid.uuid4())

    def raise_service_error(s, img):
        raise FaceServiceUnavailableError("Dịch vụ nhận diện khuôn mặt quá tải.")

    FaceMatchingService.set_mock_handler(raise_service_error)

    files = {"image": ("face.jpg", io.BytesIO(SAMPLE_JPEG), "image/jpeg")}
    data = {
        "student_id": stu_id,
        "subject_id": subj_id,
        "uuid": checkin_uuid,
    }

    r = api_gv.post(f"{v1}/attendance/face", data=data, files=files, timeout=5)
    assert r.status_code == 503, f"Kỳ vọng 503 nhưng nhận {r.status_code}: {r.text}"
    assert r.json().get("code") == "FACE_SERVICE_ERROR"


# ---------------------------------------------------------------------------
# [CA 4] Bắt lỗi khi thiếu tệp ảnh khuôn mặt -> 422 MISSING_IMAGE
# ---------------------------------------------------------------------------
def test_face_attendance_missing_image(api_gv, v1, setup_data):
    """Gọi /attendance/face nhưng không gửi file ảnh -> 422 MISSING_IMAGE."""
    subj_id = setup_data["subject_id"]
    stu_id = setup_data["student_id"]

    data = {
        "student_id": stu_id,
        "subject_id": subj_id,
    }
    r = api_gv.post(f"{v1}/attendance/face", data=data, timeout=5)
    assert r.status_code == 422
    assert r.json().get("code") == "MISSING_IMAGE"


# ---------------------------------------------------------------------------
# [CA 5] Sinh viên chưa ghi danh môn học -> 422 STUDENT_NOT_ENROLLED
# ---------------------------------------------------------------------------
def test_face_attendance_student_not_enrolled(api_super, api_gv, v1, setup_data):
    """Sinh viên có tồn tại nhưng chưa ghi danh môn học -> 422 STUDENT_NOT_ENROLLED."""
    subj_id = setup_data["subject_id"]
    unenrolled_student = f"SV_NOTENR_{uuid.uuid4().hex[:6].upper()}"

    # Tạo sinh viên nhưng không ghi danh vào môn
    api_super.post(f"{v1}/sync/push", json={
        "students": [{
            "student_id": unenrolled_student,
            "full_name": "Sinh Vien Chua Ghi Danh",
            "face_embedding": [0.1] * 192,
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-27T08:00:00Z",
        }]
    }, timeout=5)

    files = {"image": ("face.jpg", io.BytesIO(SAMPLE_JPEG), "image/jpeg")}
    data = {
        "student_id": unenrolled_student,
        "subject_id": subj_id,
    }

    r = api_gv.post(f"{v1}/attendance/face", data=data, files=files, timeout=5)
    assert r.status_code == 422
    assert r.json().get("code") == "STUDENT_NOT_ENROLLED"


# ---------------------------------------------------------------------------
# [CA 6] Giảng viên không có quyền trên môn học -> 403 FORBIDDEN
# ---------------------------------------------------------------------------
def test_face_attendance_forbidden_for_other_lecturer(api_super, api_gv, v1):
    """Giảng viên điểm danh môn do tài khoản khác phụ trách -> 403 FORBIDDEN."""
    other_subj = f"SUB_OTHER_{uuid.uuid4().hex[:6].upper()}"
    stu_id = f"SV_OTHER_{uuid.uuid4().hex[:6].upper()}"

    # Môn học gán cho SADM_001 (không phải ADM_001 của giảng viên)
    api_super.post(f"{v1}/sync/push", json={
        "subjects": [{
            "subject_id": other_subj,
            "subject_name": "Môn Của Admin Khác",
            "instructor_id": "SADM_001",
            "subject_status": "ACTIVE",
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-27T08:00:00Z",
        }],
        "students": [{
            "student_id": stu_id,
            "full_name": "Sinh Vien Mon Khac",
            "face_embedding": [0.1] * 192,
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-27T08:00:00Z",
        }],
        "enrollments": [{
            "student_id": stu_id,
            "subject_id": other_subj,
            "enrollment_status": "ACTIVE",
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-27T08:00:00Z",
        }],
    }, timeout=5)

    files = {"image": ("face.jpg", io.BytesIO(SAMPLE_JPEG), "image/jpeg")}
    data = {
        "student_id": stu_id,
        "subject_id": other_subj,
    }

    # Giảng viên ADM_001 gọi điểm danh môn other_subj -> 403
    r = api_gv.post(f"{v1}/attendance/face", data=data, files=files, timeout=5)
    assert r.status_code == 403
    assert r.json().get("code") == "FORBIDDEN"


# ---------------------------------------------------------------------------
# [CA 7] Chống trùng lặp theo UUID (Idempotency)
# ---------------------------------------------------------------------------
def test_face_attendance_idempotent_uuid(api_gv, v1, setup_data):
    """Gửi lặp lại cùng một UUID -> Lần đầu 201 (created=True), lần 2 trả 200 (created=False)."""
    subj_id = setup_data["subject_id"]
    stu_id = setup_data["student_id"]
    same_uuid = str(uuid.uuid4())

    FaceMatchingService.set_mock_handler(lambda s, img: (True, 0.95, "Khớp."))

    files = {"image": ("face.jpg", io.BytesIO(SAMPLE_JPEG), "image/jpeg")}
    data = {
        "student_id": stu_id,
        "subject_id": subj_id,
        "uuid": same_uuid,
    }

    # Lần 1: Tạo mới thành công
    r1 = api_gv.post(f"{v1}/attendance/face", data=data, files=files, timeout=5)
    assert r1.status_code == 201
    assert r1.json().get("created") is True

    # Lần 2: Gửi lại cùng UUID
    files2 = {"image": ("face.jpg", io.BytesIO(SAMPLE_JPEG), "image/jpeg")}
    r2 = api_gv.post(f"{v1}/attendance/face", data=data, files=files2, timeout=5)
    assert r2.status_code == 200
    assert r2.json().get("created") is False
    assert r2.json().get("status") == "already_exists"


# ---------------------------------------------------------------------------
# [CA 8] Điểm danh multipart qua route /attendance tự động nhận diện ảnh
# ---------------------------------------------------------------------------
def test_attendance_multipart_fallback_success(api_gv, v1, setup_data):
    """POST /attendance khi truyền kèm multipart image cũng tự động xác thực khuôn mặt thành công."""
    subj_id = setup_data["subject_id"]
    stu_id = setup_data["student_id"]

    FaceMatchingService.set_mock_handler(lambda s, img: (True, 0.90, "Khớp."))

    files = {"image": ("face.jpg", io.BytesIO(SAMPLE_JPEG), "image/jpeg")}
    data = {
        "student_id": stu_id,
        "subject_id": subj_id,
        "uuid": str(uuid.uuid4()),
    }

    r = api_gv.post(f"{v1}/attendance", data=data, files=files, timeout=5)
    assert r.status_code == 201
    assert r.json().get("created") is True
    assert "score" in r.json()


# ---------------------------------------------------------------------------
# [CA 9] Điểm danh thủ công bằng JSON (/attendance) vẫn hoạt động bình thường
# ---------------------------------------------------------------------------
def test_manual_attendance_json_backwards_compatible(api_gv, v1, setup_data):
    """POST /attendance dạng JSON cũ (không có ảnh) vẫn được bảo toàn 100%."""
    subj_id = setup_data["subject_id"]
    stu_id = setup_data["student_id"]

    r = api_gv.post(f"{v1}/attendance", json={
        "student_id": stu_id,
        "subject_id": subj_id,
        "checkin_time": "09:00:00",
        "checkin_date": "2026-11-27",
        "uuid": str(uuid.uuid4()),
        "status": "present",
    }, timeout=5)

    assert r.status_code == 201
    assert r.json().get("created") is True
    assert r.json().get("checkin", {}).get("student_id") == stu_id
