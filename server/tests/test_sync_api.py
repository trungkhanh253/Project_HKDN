import uuid
import pytest

pytestmark = pytest.mark.api


def test_sync_push_and_pull_lifecycle(api, v1):
    """Kiểm tra đẩy thêm mới, sửa, xóa mềm và kéo về qua after_seq."""
    stu_uuid = str(uuid.uuid4())
    sub_uuid = str(uuid.uuid4())
    enr_uuid = str(uuid.uuid4())

    # 1. Lấy latest_seq ban đầu
    r_init = api.get(f"{v1}/sync/pull?after_seq=0&limit=1", timeout=5)
    assert r_init.status_code == 200
    base_seq = r_init.json()["latest_seq"]

    # 2. Push thêm mới student, subject, enrollment
    r_push = api.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "student_id": "SYNC_SV01",
                    "full_name": "Sinh Vien Sync 1",
                    "email": "sync1@edu.vn",
                    "uuid": stu_uuid,
                    "updated_at": "2026-11-09T10:00:00Z",
                    "deleted_at": None,
                }
            ],
            "subjects": [
                {
                    "subject_id": "SYNC_SUB01",
                    "subject_name": "Mon Hoc Sync 1",
                    "uuid": sub_uuid,
                    "updated_at": "2026-11-09T10:00:00Z",
                    "deleted_at": None,
                }
            ],
            "enrollments": [
                {
                    "student_id": "SYNC_SV01",
                    "subject_id": "SYNC_SUB01",
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

    # 3. Push bản ghi cũ hơn (LWW conflict) -> phải nằm trong skipped
    r_old = api.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "student_id": "SYNC_SV01",
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

    # 4. Push xóa mềm (deleted_at != null) với updated_at mới hơn
    r_del = api.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "student_id": "SYNC_SV01",
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

    # 5. Pull với after_seq = base_seq -> phải thấy bản ghi đã xóa mềm và có trường has_more / next_seq
    r_pull = api.get(f"{v1}/sync/pull?after_seq={base_seq}&limit=100", timeout=5)
    assert r_pull.status_code == 200
    pull_data = r_pull.json()
    assert "next_seq" in pull_data
    assert "has_more" in pull_data
    pulled_students = [
        s for s in pull_data["changes"]["students"] if s["student_id"] == "SYNC_SV01"
    ]
    assert len(pulled_students) == 1
    assert pulled_students[0]["deleted_at"] is not None


def test_sync_push_foreign_key_error_returns_409(api, v1):
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


def test_sync_push_invalid_vector_returns_422(api, v1):
    r = api.post(
        f"{v1}/sync/push",
        json={
            "students": [
                {
                    "student_id": "BAD_VEC_01",
                    "full_name": "Sai Chieu Vector",
                    "face_embedding": [0.1, 0.2, 0.3],  # không phải 192 chiều
                }
            ]
        },
        timeout=5,
    )
    assert r.status_code == 422
    assert "error" in r.json()

