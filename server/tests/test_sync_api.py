import uuid
import pytest

pytestmark = pytest.mark.api


@pytest.fixture
def api_auth(api, auth):
    """HTTP Session có JWT, chỉ sử dụng trong test Sync."""
    session = api
    old_headers = dict(session.headers)

    session.headers.update(auth)

    try:
        yield session
    finally:
        session.headers.clear()
        session.headers.update(old_headers)


def test_sync_push_and_pull_lifecycle(api_auth, v1):
    api = api_auth

    stu_uuid = str(uuid.uuid4())
    sub_uuid = str(uuid.uuid4())
    enr_uuid = str(uuid.uuid4())

    # Tạo ID riêng cho mỗi lần chạy test
    student_id = f"SYNC_SV_{uuid.uuid4().hex[:12].upper()}"
    subject_id = f"SYNC_SUB_{uuid.uuid4().hex[:12].upper()}"

    # 1. Láº¥y latest_seq ban Ä‘áº§u
    r_init = api.get(f"{v1}/sync/pull?after_seq=0&limit=1", timeout=5)
    assert r_init.status_code == 200
    base_seq = r_init.json()["latest_seq"]

    # 2. Push thÃªm má»›i student, subject, enrollment
    r_push = api.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "student_id": student_id,
                    "full_name": "Sinh Vien Sync 1",
                    "email": "sync1@edu.vn",
                    "uuid": stu_uuid,
                    "updated_at": "2026-11-09T10:00:00Z",
                    "deleted_at": None,
                }
            ],
            "subjects": [
                {
                    "subject_id": subject_id,
                    "subject_name": "Mon Hoc Sync 1",
                    "uuid": sub_uuid,
                    "updated_at": "2026-11-09T10:00:00Z",
                    "deleted_at": None,
                }
            ],
            "enrollments": [
                {
                    "student_id": student_id,
                    "subject_id": subject_id,
                    "enrollment_status": "Enrolled",
                    "uuid": enr_uuid,
                    "updated_at": "2026-11-09T10:00:00Z",
                    "deleted_at": None,
                }
            ],
        },
        timeout=5,
    )
    assert r_push.status_code == 200
    push_data = r_push.json()
    assert push_data["applied"]["students"] == 1
    assert push_data["applied"]["subjects"] == 1
    assert push_data["applied"]["enrollments"] == 1
    assert push_data["latest_seq"] > base_seq

    # 3. Push báº£n ghi cÅ© hÆ¡n (LWW conflict) -> pháº£i náº±m trong skipped
    r_old = api.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "student_id": student_id,
                    "full_name": "Ten Cu Hon",
                    "uuid": stu_uuid,
                    "updated_at": "2026-11-09T09:00:00Z",
                }
            ]
        },
        timeout=5,
    )
    assert r_old.status_code == 200
    assert r_old.json()["skipped"]["students"] == 1

    # 4. Push xÃ³a má»m (deleted_at != null) vá»›i updated_at má»›i hÆ¡n
    r_del = api.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "student_id": student_id,
                    "full_name": "Sinh Vien Sync 1 (Da Xoa)",
                    "uuid": stu_uuid,
                    "updated_at": "2026-11-09T11:00:00Z",
                    "deleted_at": "2026-11-09T11:00:00Z",
                }
            ]
        },
        timeout=5,
    )
    assert r_del.status_code == 200
    assert r_del.json()["applied"]["students"] == 1

    # 5. Pull vá»›i after_seq = base_seq -> pháº£i tháº¥y báº£n ghi Ä‘Ã£ xÃ³a má»m vÃ  cÃ³ trÆ°á»ng has_more / next_seq
    r_pull = api.get(f"{v1}/sync/pull?after_seq={base_seq}&limit=100", timeout=5)
    assert r_pull.status_code == 200
    pull_data = r_pull.json()
    assert "next_seq" in pull_data
    assert "has_more" in pull_data
    pulled_students = [
        s for s in pull_data["changes"]["students"] if s["student_id"] == student_id
    ]
    assert len(pulled_students) == 1
    assert pulled_students[0]["deleted_at"] is not None


def test_sync_push_foreign_key_error_returns_409(api_auth, v1):
    api = api_auth
    r = api.post(
        f"{v1}/sync/push",
        json={
            "enrollments": [
                {
                    "student_id": "KHONG_TON_TAI_999",
                    "subject_id": "MON_KHONG_TON_TAI_999",
                    "enrollment_status": "Enrolled",
                }
            ]
        },
        timeout=5,
    )
    assert r.status_code == 409
    assert "error" in r.json()


def test_sync_push_invalid_vector_returns_422(api_auth, v1):
    api = api_auth
    r = api.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "student_id": "BAD_VEC_01",
                    "full_name": "Sai Chieu Vector",
                    "face_embedding": [0.1, 0.2, 0.3],  # khÃ´ng pháº£i 192 chiá»u
                }
            ]
        },
        timeout=5,
    )
    assert r.status_code == 422
    assert "error" in r.json()


def test_sync_android_outbox_push_and_since_seq_pull(api_auth, v1):
    api = api_auth
    """Kiá»ƒm tra tÆ°Æ¡ng thÃ­ch Ä‘á»‹nh dáº¡ng SyncPushRequest & SyncPullResponse cá»§a Android (since_seq)."""
    chg_id = f"chg_{uuid.uuid4().hex[:8]}"
    stu_uuid = str(uuid.uuid4())
    stu_id = f"AND_{uuid.uuid4().hex[:6].upper()}"

    r_status = api.get(f"{v1}/sync/status", timeout=5)
    assert r_status.status_code == 200
    since_seq = r_status.json()["latest_seq"]

    r_push = api.post(
        f"{v1}/sync/push",
        json={
            "device_id": "android_pixel_test",
            "changes": [
                {
                    "change_id": chg_id,
                    "uuid": stu_uuid,
                    "table_name": "students",
                    "operation": "INSERT",
                    "payload": {
                        "student_id": stu_id,
                        "full_name": "Sinh Vien Android Outbox",
                        "email": "android@edu.vn",
                        "face_embedding": [0.02] * 192,
                    },
                    "updated_at": 1762689600000,
                }
            ],
        },
        timeout=5,
    )
    assert r_push.status_code == 200
    p_json = r_push.json()
    assert chg_id in p_json["synced_change_ids"]
    assert p_json["applied"]["students"] == 1

    r_pull = api.get(f"{v1}/sync/pull?since_seq={since_seq}&limit=50", timeout=5)
    assert r_pull.status_code == 200
    pull_json = r_pull.json()
    assert "new_seq" in pull_json
    assert isinstance(pull_json["changes"], list)
    matched = [c for c in pull_json["changes"] if c["uuid"] == stu_uuid]
    assert len(matched) == 1
    assert matched[0]["table_name"] == "students"
    assert matched[0]["operation"] == "INSERT"


def test_sync_pull_pagination_has_more_and_next_seq(api_auth, v1):
    """Kiá»ƒm tra phÃ¢n trangå¢žé‡ (limit nhá» -> has_more=True vÃ  dÃ¹ng next_seq kÃ©o tiáº¿p)."""
    api = api_auth
    r_pull = api.get(f"{v1}/sync/pull?after_seq=0&limit=1", timeout=5)
    assert r_pull.status_code == 200
    data = r_pull.json()
    assert data["next_seq"] >= 1
    assert "has_more" in data


def test_sync_push_idempotent_duplicate_does_not_create_extra_row(api_auth, v1):
    """Kiá»ƒm tra tÃ­nh Idempotent: Ä‘áº©y láº¡i cÃ¹ng 1 báº£n ghi vá»›i cÃ¹ng timestamp khÃ´ng sinh báº£n ghi trÃ¹ng."""
    api = api_auth
    stu_uuid = str(uuid.uuid4())
    stu_id = f"IDEM_{uuid.uuid4().hex[:6].upper()}"
    payload = {
        "students": [
            {
                "student_id": stu_id,
                "full_name": "Sinh Vien Idempotent",
                "uuid": stu_uuid,
                "updated_at": "2026-11-09T12:00:00Z",
            }
        ]
    }
    r1 = api.post(f"{v1}/sync/push", json=payload, timeout=5)
    assert r1.status_code == 200
    r2 = api.post(f"{v1}/sync/push", json=payload, timeout=5)
    assert r2.status_code == 200

    r_list = api.get(f"{v1}/students", timeout=5)
    assert r_list.status_code == 200
    matches = [s for s in r_list.json()["students"] if s["student_id"] == stu_id]
    assert len(matches) == 1



