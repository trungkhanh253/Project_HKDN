import os
import uuid
import pytest
import requests

pytestmark = pytest.mark.api

SUPER_EMAIL = os.getenv("TEST_ADMIN_EMAIL", "admin@hkdn.edu.vn")
SUPER_PASSWORD = os.getenv("TEST_ADMIN_PASSWORD", "admin123")
GV_EMAIL = "lecturer@hkdn.edu.vn"
GV_PASSWORD = "lecturer123"


@pytest.fixture
def api_auth(base_url, v1):
    """Independent Session authenticated as SUPER_ADMIN."""
    s = requests.Session()
    r = s.post(f"{v1}/auth/login", json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD}, timeout=5)
    assert r.status_code == 200, f"Đăng nhập Super Admin thất bại: {r.text}"
    token = r.json()["access_token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture
def lecturer_auth(base_url, v1):
    """Independent Session authenticated as Giảng viên (ADM_001)."""
    s = requests.Session()
    r = s.post(f"{v1}/auth/login", json={"email": GV_EMAIL, "password": GV_PASSWORD}, timeout=5)
    assert r.status_code == 200, f"Đăng nhập Giảng viên thất bại: {r.text}"
    token = r.json()["access_token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _get_students_from_pull(pull_data):
    changes = pull_data.get("changes", [])
    if isinstance(changes, list):
        return [c.get("data", c.get("payload", {})) for c in changes if c.get("table", c.get("table_name")) == "students"]
    elif isinstance(changes, dict):
        return changes.get("students", [])
    return []


# ---------------------------------------------------------------------------
# [TEST 1] Đẩy vector 192 số & checkin_password hash -> kéo về đủ 192 số (cả outbox & gộp bảng)
# ---------------------------------------------------------------------------
def test_face_vector_and_checkin_password_sync_pull(api_auth, v1):
    """Task 4 (TV3) & Task TV5: /sync/pull trả face_embedding (192 số) và checkin_password (dạng hash) cho bảng students."""
    stu_uuid = str(uuid.uuid4())
    student_id = f"SV_FACE_{uuid.uuid4().hex[:10].upper()}"
    vector_192 = [round(0.01 * (i % 10), 4) for i in range(192)]
    checkin_pwd_hash = "$checkin$1$600000$testsaltsalt$abcdef1234567890"

    r_init = api_auth.get(f"{v1}/sync/status")
    base_seq = r_init.json().get("latest_seq", 0)

    # 1. Push student với vector 192 chiều và checkin_password dạng hash
    r_push = api_auth.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "uuid": stu_uuid,
                    "student_id": student_id,
                    "full_name": "Nguyen Van Face",
                    "face_embedding": vector_192,
                    "checkin_password": checkin_pwd_hash,
                    "updated_at": "2026-11-20T10:00:00Z",
                }
            ]
        },
    )
    assert r_push.status_code == 200, f"Push thất bại: {r_push.text}"

    # 2. Pull theo dạng gộp theo bảng (after_seq)
    r_pull = api_auth.get(f"{v1}/sync/pull?after_seq={base_seq}&limit=500")
    assert r_pull.status_code == 200
    pull_data = r_pull.json()

    students = _get_students_from_pull(pull_data)
    matched = [s for s in students if s.get("student_id") == student_id]
    assert len(matched) >= 1, f"Không tìm thấy sinh viên {student_id} trong /sync/pull"

    stu_pulled = matched[-1]
    assert stu_pulled.get("face_embedding") is not None, "face_embedding bị thiếu trong pull"
    assert len(stu_pulled["face_embedding"]) == 192, f"Kỳ vọng 192 chiều, nhận được {len(stu_pulled['face_embedding'])}"
    assert stu_pulled.get("checkin_password") == checkin_pwd_hash

    # 3. Pull theo dạng phẳng (since_seq / format=flat)
    r_flat = api_auth.get(f"{v1}/sync/pull?since_seq={base_seq}&limit=500")
    assert r_flat.status_code == 200
    flat_students = _get_students_from_pull(r_flat.json())
    flat_matched = [s for s in flat_students if s.get("student_id") == student_id]
    assert len(flat_matched) >= 1, "Không tìm thấy sinh viên trong flat pull"
    assert len(flat_matched[-1].get("face_embedding", [])) == 192
    assert flat_matched[-1].get("checkin_password") == checkin_pwd_hash


# ---------------------------------------------------------------------------
# [TEST 2] Đăng ký lại khuôn mặt: vector mới ghi đè vector cũ theo uuid
# ---------------------------------------------------------------------------
def test_face_vector_re_registration_overwrites_old_vector(api_auth, v1):
    """Task 5 (TV3): Khi đăng ký lại khuôn mặt, vector mới ghi đè vector cũ theo uuid."""
    stu_uuid = str(uuid.uuid4())
    student_id = f"SV_REREG_{uuid.uuid4().hex[:10].upper()}"

    v1_old = [0.1] * 192
    v2_new = [0.9] * 192

    base_seq = api_auth.get(f"{v1}/sync/status").json().get("latest_seq", 0)

    # Lần 1: Đăng ký vector cũ lúc 10:00
    r1 = api_auth.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "uuid": stu_uuid,
                    "student_id": student_id,
                    "full_name": "SV Dang Ky Lai",
                    "face_embedding": v1_old,
                    "updated_at": "2026-11-20T10:00:00Z",
                }
            ]
        },
    )
    assert r1.status_code == 200

    # Lần 2: Đăng ký lại khuôn mặt với vector mới lúc 11:00 (updated_at mới hơn)
    r2 = api_auth.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "uuid": stu_uuid,
                    "student_id": student_id,
                    "full_name": "SV Dang Ky Lai",
                    "face_embedding": v2_new,
                    "updated_at": "2026-11-20T11:00:00Z",
                }
            ]
        },
    )
    assert r2.status_code == 200

    # Kéo về kiểm tra: vector trên Server phải là v2_new (ghi đè thành công)
    r_pull = api_auth.get(f"{v1}/sync/pull?since_seq={base_seq}&limit=500")
    assert r_pull.status_code == 200
    students = _get_students_from_pull(r_pull.json())
    matched = [s for s in students if s.get("student_id") == student_id]
    assert len(matched) >= 1
    pulled_vec = matched[-1]["face_embedding"]
    assert pytest.approx(pulled_vec[0], 0.01) == 0.9, "Vector mới chưa ghi đè vector cũ"


# ---------------------------------------------------------------------------
# [TEST 3] Bản cập nhật có updated_at cũ hơn bản hiện có trên server sẽ bị bỏ qua
# ---------------------------------------------------------------------------
def test_face_vector_older_timestamp_is_ignored(api_auth, v1):
    """Task 5 (TV3): Bản cập nhật có updated_at cũ hơn bản hiện có trên server sẽ bị bỏ qua."""
    stu_uuid = str(uuid.uuid4())
    student_id = f"SV_LWW_{uuid.uuid4().hex[:10].upper()}"

    v_current = [0.8] * 192
    v_stale = [0.2] * 192

    base_seq = api_auth.get(f"{v1}/sync/status").json().get("latest_seq", 0)

    # Đăng ký bản hiện tại lúc 12:00
    r1 = api_auth.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "uuid": stu_uuid,
                    "student_id": student_id,
                    "full_name": "SV LWW Test",
                    "face_embedding": v_current,
                    "updated_at": "2026-11-20T12:00:00Z",
                }
            ]
        },
    )
    assert r1.status_code == 200

    # Cố tình gửi bản cũ hơn lúc 08:00
    r2 = api_auth.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "uuid": stu_uuid,
                    "student_id": student_id,
                    "full_name": "SV LWW Test",
                    "face_embedding": v_stale,
                    "updated_at": "2026-11-20T08:00:00Z",
                }
            ]
        },
    )
    assert r2.status_code == 200
    assert r2.json().get("skipped", {}).get("students", 0) >= 1, "Bản cũ hơn phải bị bỏ qua (skipped)"

    # Kéo về kiểm tra: vector trên Server vẫn giữ nguyên v_current (0.8)
    r_pull = api_auth.get(f"{v1}/sync/pull?since_seq={base_seq}&limit=500")
    students = _get_students_from_pull(r_pull.json())
    matched = [s for s in students if s.get("student_id") == student_id]
    assert len(matched) >= 1
    pulled_vec = matched[-1]["face_embedding"]
    assert pytest.approx(pulled_vec[0], 0.01) == 0.8, "Vector cũ hơn không được phép ghi đè"


# ---------------------------------------------------------------------------
# [TEST 4] Vector sai số chiều (khác 192) bị từ chối với HTTP 422
# ---------------------------------------------------------------------------
def test_face_vector_invalid_dimensions_returns_422(api_auth, v1):
    """TV5: Vector sai số chiều (khác 192) bị từ chối với HTTP 422."""
    r = api_auth.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "student_id": f"SV_ERR_{uuid.uuid4().hex[:8]}",
                    "full_name": "Vector Loi",
                    "face_embedding": [0.1] * 50,  # Sai: chỉ có 50 chiều
                }
            ]
        },
    )
    assert r.status_code in (400, 422), f"Kỳ vọng 422 hoặc 400 nhưng nhận HTTP {r.status_code}"


# ---------------------------------------------------------------------------
# [TEST 5] Vector chỉ có ở bảng students, KHÔNG có ở các bảng khác
# ---------------------------------------------------------------------------
def test_face_embedding_only_in_students_table(api_auth, v1):
    """TV5: Các bảng khác (subjects, admin, enrollments, checkin_history...) không được chứa face_embedding."""
    r = api_auth.get(f"{v1}/sync/pull?after_seq=0&limit=500")
    assert r.status_code == 200

    data = r.json()
    changes = data.get("changes", {})
    if isinstance(changes, dict):
        for table_name, rows in changes.items():
            if table_name == "students":
                continue
            for row in rows:
                assert "face_embedding" not in row, f"Bảng '{table_name}' không được chứa face_embedding"
    elif isinstance(changes, list):
        for item in changes:
            tbl = item.get("table", item.get("table_name"))
            if tbl == "students":
                continue
            row_data = item.get("data", item.get("payload", {}))
            assert "face_embedding" not in row_data, f"Bảng '{tbl}' không được chứa face_embedding"


# ---------------------------------------------------------------------------
# [TEST 6] Giảng viên ngoài môn KHÔNG nhận được sinh viên / vector của sinh viên đó
# ---------------------------------------------------------------------------
def test_lecturer_outside_subject_cannot_see_vector(api_auth, lecturer_auth, v1):
    """TV5: Giảng viên chỉ nhận sinh viên thuộc môn của mình khi sync pull."""
    # Tạo môn học do SUPER_ADMIN quản lý (không phải ADM_001)
    other_subj = f"SUB_OTHER_{uuid.uuid4().hex[:6].upper()}"
    stu_other = f"SV_OTHER_{uuid.uuid4().hex[:6].upper()}"

    r_push = api_auth.post(f"{v1}/sync/push", json={
        "subjects": [{
            "subject_id": other_subj,
            "subject_name": "Môn của Admin khác",
            "instructor_id": "SADM_001",
            "subject_status": "ACTIVE",
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-20T10:00:00Z",
        }],
        "students": [{
            "student_id": stu_other,
            "full_name": "Sinh Vien Cua Admin Khac",
            "face_embedding": [0.3] * 192,
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-20T10:00:00Z",
        }],
        "enrollments": [{
            "student_id": stu_other,
            "subject_id": other_subj,
            "enrollment_status": "ACTIVE",
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-20T10:00:00Z",
        }],
    })
    assert r_push.status_code == 200

    # Giảng viên ADM_001 kéo pull -> không được thấy sinh viên stu_other
    r_gv_pull = lecturer_auth.get(f"{v1}/sync/pull?since_seq=0&limit=500")
    assert r_gv_pull.status_code == 200
    gv_students = _get_students_from_pull(r_gv_pull.json())
    matched = [s for s in gv_students if s.get("student_id") == stu_other]
    assert len(matched) == 0, f"Giảng viên ngoài môn vẫn thấy sinh viên {stu_other}!"


# ---------------------------------------------------------------------------
# [TEST 7] checkin_password dạng thô tự động hash, dạng hash không bị băm lại
# ---------------------------------------------------------------------------
def test_checkin_password_hash_handling(api_auth, v1):
    """TV5: checkin_password thô -> hash; checkin_password dạng hash ($checkin$, pbkdf2) giữ nguyên."""
    raw_pwd = "password123"
    pre_hashed = "$checkin$1$600000$salt$hashvalue12345"

    sid_raw = f"SV_RAW_{uuid.uuid4().hex[:6].upper()}"
    sid_hash = f"SV_HASH_{uuid.uuid4().hex[:6].upper()}"

    base_seq = api_auth.get(f"{v1}/sync/status").json().get("latest_seq", 0)

    r_push = api_auth.post(f"{v1}/sync/push", json={
        "students": [
            {
                "student_id": sid_raw,
                "full_name": "Sinh Vien Mat Khau Tho",
                "checkin_password": raw_pwd,
                "uuid": str(uuid.uuid4()),
                "updated_at": "2026-11-20T10:00:00Z",
            },
            {
                "student_id": sid_hash,
                "full_name": "Sinh Vien Mat Khau Da Hash",
                "checkin_password": pre_hashed,
                "uuid": str(uuid.uuid4()),
                "updated_at": "2026-11-20T10:00:00Z",
            },
        ]
    })
    assert r_push.status_code == 200

    r_pull = api_auth.get(f"{v1}/sync/pull?since_seq={base_seq}&limit=500")
    assert r_pull.status_code == 200
    students = _get_students_from_pull(r_pull.json())

    stu_raw = next((s for s in students if s.get("student_id") == sid_raw), None)
    stu_hash = next((s for s in students if s.get("student_id") == sid_hash), None)

    assert stu_raw is not None, f"Không tìm thấy sinh viên mật khẩu thô {sid_raw}"
    assert stu_hash is not None, f"Không tìm thấy sinh viên mật khẩu hash {sid_hash}"

    # Mật khẩu thô không bao giờ được trả về dưới dạng thô
    assert stu_raw.get("checkin_password") != raw_pwd
    assert stu_raw.get("checkin_password").startswith("pbkdf2_sha256$")

    # Mật khẩu đã hash giữ nguyên
    assert stu_hash.get("checkin_password") == pre_hashed


# ---------------------------------------------------------------------------
# [TEST 8] API cho Web (GET /students) KHÔNG trả face_embedding hay checkin_password
# ---------------------------------------------------------------------------
def test_web_api_students_does_not_expose_vector_or_password(api_auth, v1):
    """TV5: API Web GET /students không được trả face_embedding hay checkin_password."""
    r = api_auth.get(f"{v1}/students?limit=50")
    assert r.status_code == 200

    data = r.json()
    items = data.get("items", data if isinstance(data, list) else [])
    for student in items:
        assert "face_embedding" not in student, f"Lộ face_embedding trên GET /students (id={student.get('student_id')})"
        assert "checkin_password" not in student, f"Lộ checkin_password trên GET /students (id={student.get('student_id')})"
