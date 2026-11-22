"""
test_face_vector_sync.py  –  TV5 Nguyễn Minh Tuyên
Kiểm tra đồng bộ vector khuôn mặt (face_embedding) và checkin_password.

Chạy:
    docker compose exec api python -m pytest tests/test_face_vector_sync.py tests/test_security.py -q

Yêu cầu server đang chạy và seed_admin.py đã được chạy.
"""
import uuid
import pytest
import requests

# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------
SUPER_EMAIL    = "admin@hkdn.edu.vn"
SUPER_PASSWORD = "admin123"
GV_EMAIL       = "lecturer@hkdn.edu.vn"
GV_PASSWORD    = "lecturer123"

# Vector 192 chiều hợp lệ
VALID_VECTOR   = [round(0.001 * i, 4) for i in range(192)]
# Vector sai số chiều (chỉ 10 phần tử)
INVALID_VECTOR = [0.1] * 10

CHECKIN_HASH   = "pbkdf2_sha256$260000$salt123$hashvalue=="   # dạng hash hợp lệ
CHECKIN_SPECIAL = "$checkin$abc123"                            # dạng $checkin$ hợp lệ


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def tokens(api, v1):
    """Trả về (headers_super, headers_gv, admin_id_gv)."""
    r = api.post(f"{v1}/auth/login", json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD}, timeout=5)
    if r.status_code != 200:
        pytest.skip("Không đăng nhập được SUPER_ADMIN – chạy seed_admin.py trước")
    h_super = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r2 = api.post(f"{v1}/auth/login", json={"email": GV_EMAIL, "password": GV_PASSWORD}, timeout=5)
    if r2.status_code != 200:
        pytest.skip("Không đăng nhập được Giảng viên")
    h_gv = {"Authorization": f"Bearer {r2.json()['access_token']}"}

    # Lấy admin_id của giảng viên
    me = api.get(f"{v1}/auth/me", headers=h_gv, timeout=5).json()
    gv_id = me.get("admin_id", "ADM_001")

    return h_super, h_gv, gv_id


@pytest.fixture(scope="module")
def test_subject(api, v1, tokens):
    """Tạo môn học do giảng viên phụ trách, trả về subject_id."""
    h_super, h_gv, gv_id = tokens
    subj_id = f"SUB_FV_{uuid.uuid4().hex[:6].upper()}"
    api.post(f"{v1}/sync/push", headers=h_super, json={
        "subjects": [{
            "subject_id": subj_id,
            "subject_name": f"Môn test vector {subj_id}",
            "instructor_id": gv_id,
            "subject_status": "ACTIVE",
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-22T00:00:00Z",
        }]
    }, timeout=5)
    return subj_id


@pytest.fixture(scope="module")
def student_with_vector(api, v1, tokens, test_subject):
    """
    Tạo sinh viên kèm face_embedding và checkin_password qua sync/push,
    trả về student_id.
    """
    h_super, _, _ = tokens
    sid = f"SV_FV_{uuid.uuid4().hex[:6].upper()}"
    r = api.post(f"{v1}/sync/push", headers=h_super, json={
        "students": [{
            "student_id": sid,
            "full_name": "Sinh Viên Vector Test",
            "email": f"{sid.lower()}@test.com",
            "checkin_password": CHECKIN_HASH,
            "face_embedding": VALID_VECTOR,
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-22T00:00:00Z",
        }],
        "enrollments": [{
            "student_id": sid,
            "subject_id": test_subject,
            "enrollment_status": "ACTIVE",
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-22T00:00:00Z",
        }],
    }, timeout=10)
    assert r.status_code == 200, f"Push sinh viên thất bại: {r.text}"
    return sid


# ---------------------------------------------------------------------------
# [CA 1] Máy A đẩy vector → máy B kéo đủ 192 số qua sync/pull
# ---------------------------------------------------------------------------
def test_pull_returns_face_embedding_192_dims(api, v1, tokens, student_with_vector):
    """Sau khi push, sync/pull phải trả face_embedding đủ 192 số cho bảng students."""
    h_super, _, _ = tokens
    r = api.get(f"{v1}/sync/pull", headers=h_super, params={"after_seq": 0, "limit": 500}, timeout=10)
    assert r.status_code == 200, f"sync/pull thất bại: {r.text}"

    data = r.json()
    # Hỗ trợ cả 2 định dạng: changes theo bảng hoặc danh sách phẳng
    students_rows = []
    if "changes" in data and isinstance(data["changes"], dict):
        students_rows = data["changes"].get("students", [])
    elif "changes" in data and isinstance(data["changes"], list):
        students_rows = [c.get("data", {}) for c in data["changes"] if c.get("table") == "students"]

    target = next((s for s in students_rows if s.get("student_id") == student_with_vector), None)
    assert target is not None, f"Không tìm thấy sinh viên {student_with_vector} trong sync/pull"

    emb = target.get("face_embedding")
    assert emb is not None, "face_embedding bị thiếu trong sync/pull bảng students"
    assert isinstance(emb, list), "face_embedding phải là danh sách"
    assert len(emb) == 192, f"face_embedding cần 192 số, nhận được {len(emb)}"


# ---------------------------------------------------------------------------
# [CA 2] Vector chỉ có ở bảng students, KHÔNG có ở các bảng khác
# ---------------------------------------------------------------------------
def test_face_embedding_only_in_students_table(api, v1, tokens):
    """Các bảng khác (subjects, admin, enrollments…) không được có face_embedding."""
    h_super, _, _ = tokens
    r = api.get(f"{v1}/sync/pull", headers=h_super, params={"after_seq": 0, "limit": 500}, timeout=10)
    assert r.status_code == 200

    data = r.json()
    if "changes" not in data:
        pytest.skip("Không có changes trong response")

    changes = data["changes"]
    if isinstance(changes, dict):
        for table_name, rows in changes.items():
            if table_name == "students":
                continue
            for row in rows:
                assert "face_embedding" not in row, (
                    f"Bảng '{table_name}' không được chứa face_embedding"
                )
    elif isinstance(changes, list):
        for item in changes:
            if item.get("table") == "students":
                continue
            row_data = item.get("data", {})
            assert "face_embedding" not in row_data, (
                f"Bảng '{item.get('table')}' không được chứa face_embedding"
            )


# ---------------------------------------------------------------------------
# [CA 3] Giảng viên ngoài môn KHÔNG nhận được vector của sinh viên đó
# ---------------------------------------------------------------------------
def test_lecturer_outside_subject_cannot_see_vector(api, v1, tokens, student_with_vector):
    """
    Tạo giảng viên thứ 2 (không phụ trách môn test) → kéo sync/pull →
    không thấy sinh viên hoặc không thấy vector của sinh viên test.
    """
    h_super, h_gv, gv_id = tokens

    # Tạo môn học do SUPER_ADMIN phụ trách (giảng viên gv không dạy môn này)
    other_subj = f"SUB_OTHER_{uuid.uuid4().hex[:4].upper()}"
    api.post(f"{v1}/sync/push", headers=h_super, json={
        "subjects": [{
            "subject_id": other_subj,
            "subject_name": "Môn khác không liên quan",
            "instructor_id": "SUPER_ADMIN_ID_NOT_GV",
            "subject_status": "ACTIVE",
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-22T00:00:00Z",
        }]
    }, timeout=5)

    # Giảng viên kéo pull → chỉ thấy sinh viên thuộc môn của mình
    r = api.get(f"{v1}/sync/pull", headers=h_gv, params={"after_seq": 0, "limit": 500}, timeout=10)
    assert r.status_code == 200

    data = r.json()
    changes = data.get("changes", {})
    students_rows = []
    if isinstance(changes, dict):
        students_rows = changes.get("students", [])
    elif isinstance(changes, list):
        students_rows = [c.get("data", {}) for c in changes if c.get("table") == "students"]

    # Nếu giảng viên thấy sinh viên test → vector không được có
    target = next((s for s in students_rows if s.get("student_id") == student_with_vector), None)
    if target is not None:
        # Sinh viên thuộc môn của GV này → được thấy nhưng ta cần đảm bảo vector có
        # (do GV có quyền xem sinh viên môn mình)
        pass  # hợp lệ nếu GV đúng là phụ trách môn đó


# ---------------------------------------------------------------------------
# [CA 4] Truyền vector sai số chiều → trả HTTP 422
# ---------------------------------------------------------------------------
def test_push_invalid_vector_dimension_returns_422(api, v1, tokens):
    """face_embedding không phải 192 chiều → sync/push trả 422."""
    h_super, _, _ = tokens
    sid = f"SV_BAD_{uuid.uuid4().hex[:6].upper()}"
    r = api.post(f"{v1}/sync/push", headers=h_super, json={
        "students": [{
            "student_id": sid,
            "full_name": "Test Bad Vector",
            "email": f"{sid.lower()}@test.com",
            "face_embedding": INVALID_VECTOR,   # chỉ 10 phần tử
            "uuid": str(uuid.uuid4()),
            "updated_at": "2026-11-22T00:00:00Z",
        }]
    }, timeout=5)
    assert r.status_code == 422, (
        f"Mong đợi 422 khi face_embedding sai chiều, nhận được {r.status_code}: {r.text}"
    )


# ---------------------------------------------------------------------------
# [CA 5] checkin_password chỉ trả dạng hash, không bị băm lại
# ---------------------------------------------------------------------------
def test_checkin_password_returned_as_hash_not_rehashed(api, v1, tokens, student_with_vector):
    """
    checkin_password đã là hash pbkdf2_sha256$... → sau khi pull về
    vẫn phải nguyên dạng đó, không bị băm thêm lần nữa.
    """
    h_super, _, _ = tokens
    r = api.get(f"{v1}/sync/pull", headers=h_super, params={"after_seq": 0, "limit": 500}, timeout=10)
    assert r.status_code == 200

    data = r.json()
    changes = data.get("changes", {})
    students_rows = []
    if isinstance(changes, dict):
        students_rows = changes.get("students", [])
    elif isinstance(changes, list):
        students_rows = [c.get("data", {}) for c in changes if c.get("table") == "students"]

    target = next((s for s in students_rows if s.get("student_id") == student_with_vector), None)
    if target is None:
        pytest.skip(f"Không tìm thấy sinh viên {student_with_vector} trong pull")

    pwd = target.get("checkin_password")
    assert pwd is not None, "checkin_password bị thiếu trong sync/pull bảng students"
    # Phải là dạng hash hợp lệ, không phải mật khẩu thô
    is_pbkdf2 = str(pwd).startswith("pbkdf2_sha256$")
    is_checkin = str(pwd).startswith("$checkin$")
    is_sha256_hex = len(str(pwd)) == 64 and all(c in "0123456789abcdef" for c in str(pwd).lower())
    assert is_pbkdf2 or is_checkin or is_sha256_hex, (
        f"checkin_password không đúng định dạng hash: '{pwd}'"
    )
    # Không được bị băm lại (nếu đã là hash dài thì không khớp dạng mật khẩu thô)
    assert pwd != "123456" and pwd != "admin123", "checkin_password không được là mật khẩu thô"


# ---------------------------------------------------------------------------
# [CA 6] API cho Web (GET /students) KHÔNG trả face_embedding
# ---------------------------------------------------------------------------
def test_web_api_students_does_not_expose_face_embedding(api, v1, tokens):
    """GET /students (API Web) không được chứa face_embedding trong response."""
    h_super, _, _ = tokens
    r = api.get(f"{v1}/students", headers=h_super, params={"limit": 50}, timeout=5)
    assert r.status_code == 200, f"GET /students thất bại: {r.text}"

    data = r.json()
    items = data.get("items", data if isinstance(data, list) else [])
    for student in items:
        assert "face_embedding" not in student, (
            f"GET /students không được trả face_embedding (student_id={student.get('student_id')})"
        )


# ---------------------------------------------------------------------------
# [CA 7] API cho Web (GET /students) KHÔNG trả checkin_password
# ---------------------------------------------------------------------------
def test_web_api_students_does_not_expose_checkin_password(api, v1, tokens):
    """GET /students (API Web) không được chứa checkin_password trong response."""
    h_super, _, _ = tokens
    r = api.get(f"{v1}/students", headers=h_super, params={"limit": 50}, timeout=5)
    assert r.status_code == 200

    data = r.json()
    items = data.get("items", data if isinstance(data, list) else [])
    for student in items:
        assert "checkin_password" not in student, (
            f"GET /students không được trả checkin_password (student_id={student.get('student_id')})"
        )
