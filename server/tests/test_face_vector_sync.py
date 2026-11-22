import uuid
import pytest

pytestmark = pytest.mark.api


@pytest.fixture
def api_auth(api, auth):
    session = api
    old_headers = dict(session.headers)
    session.headers.update(auth)
    try:
        yield session
    finally:
        session.headers.clear()
        session.headers.update(old_headers)


def _get_students_from_pull(pull_data):
    changes = pull_data.get("changes", [])
    if isinstance(changes, list):
        return [c.get("payload", {}) for c in changes if c.get("table_name") == "students"]
    elif isinstance(changes, dict):
        return changes.get("students", [])
    return []


def test_face_vector_and_checkin_password_sync_pull(api_auth, v1):
    """Task 4: /sync/pull trả face_embedding (192 số) và checkin_password (dạng hash) cho bảng students."""
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

    # 2. Pull theo dạng danh sách
    r_pull = api_auth.get(f"{v1}/sync/pull?since_seq={base_seq}")
    assert r_pull.status_code == 200
    pull_data = r_pull.json()

    students = _get_students_from_pull(pull_data)
    matched = [s for s in students if s.get("student_id") == student_id]
    assert len(matched) == 1, f"Không tìm thấy sinh viên {student_id} trong /sync/pull"

    stu_pulled = matched[0]
    assert stu_pulled.get("face_embedding") is not None
    assert len(stu_pulled["face_embedding"]) == 192
    assert stu_pulled.get("checkin_password") == checkin_pwd_hash

    # 3. Pull theo dạng phẳng (outbox flat)
    r_flat = api_auth.get(f"{v1}/sync/pull?since_seq={base_seq}&format=flat")
    assert r_flat.status_code == 200
    flat_students = _get_students_from_pull(r_flat.json())
    flat_matched = [s for s in flat_students if s.get("student_id") == student_id]
    assert len(flat_matched) >= 1
    assert len(flat_matched[0].get("face_embedding", [])) == 192
    assert flat_matched[0].get("checkin_password") == checkin_pwd_hash


def test_face_vector_re_registration_overwrites_old_vector(api_auth, v1):
    """Task 5: Khi đăng ký lại khuôn mặt, vector mới ghi đè vector cũ theo uuid."""
    stu_uuid = str(uuid.uuid4())
    student_id = f"SV_REREG_{uuid.uuid4().hex[:10].upper()}"

    v1_old = [0.1] * 192
    v2_new = [0.9] * 192

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
    r_pull = api_auth.get(f"{v1}/sync/pull?since_seq=0&limit=500")
    assert r_pull.status_code == 200
    students = _get_students_from_pull(r_pull.json())
    matched = [s for s in students if s.get("student_id") == student_id]
    assert len(matched) >= 1
    pulled_vec = matched[-1]["face_embedding"]
    assert pytest.approx(pulled_vec[0], 0.01) == 0.9, "Vector mới chưa ghi đè vector cũ"


def test_face_vector_older_timestamp_is_ignored(api_auth, v1):
    """Task 5: Bản cập nhật có updated_at cũ hơn bản hiện có trên server sẽ bị bỏ qua."""
    stu_uuid = str(uuid.uuid4())
    student_id = f"SV_LWW_{uuid.uuid4().hex[:10].upper()}"

    v_current = [0.8] * 192
    v_stale = [0.2] * 192

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
    r_pull = api_auth.get(f"{v1}/sync/pull?since_seq=0&limit=500")
    students = _get_students_from_pull(r_pull.json())
    matched = [s for s in students if s.get("student_id") == student_id]
    assert len(matched) >= 1
    pulled_vec = matched[-1]["face_embedding"]
    assert pytest.approx(pulled_vec[0], 0.01) == 0.8, "Vector cũ hơn không được phép ghi đè"


def test_face_vector_invalid_dimensions_returns_422(api_auth, v1):
    """Vector sai số chiều (khác 192) bị từ chối với HTTP 422."""
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
