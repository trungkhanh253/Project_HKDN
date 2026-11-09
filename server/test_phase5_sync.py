"""
Script kiểm tra toàn diện Nhóm Server - Giai đoạn 5 (Đồng bộ 2 chiều: sync/push & sync/pull):
Chạy bằng lệnh:
    docker.exe compose exec api python test_phase5_sync.py
"""
import os
import sys
import uuid
import requests

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:5000").rstrip("/")
API_V1 = f"{BASE_URL}/api/v1"


def run_phase5_sync_check():
    print("=" * 75)
    print(" KIỂM TRA SERVER GIAI ĐOẠN 5: ĐỒNG BỘ 2 CHIỀU (SYNC/PUSH & SYNC/PULL)")
    print("=" * 75)

    # 1. Lấy trạng thái sequence ban đầu
    r_init = requests.get(f"{API_V1}/sync/pull?after_seq=0&limit=1", timeout=5)
    assert r_init.status_code == 200
    base_seq = r_init.json()["latest_seq"]
    print(f"[1] Kiểm tra mốc Sequence hiện tại (base_seq)      : OK (latest_seq = {base_seq})")

    stu_uuid = str(uuid.uuid4())
    sub_uuid = str(uuid.uuid4())
    enr_uuid = str(uuid.uuid4())
    run_tag = uuid.uuid4().hex[:6].upper()
    stu_id = f"P5_SV_{run_tag}"
    sub_id = f"P5_SUB_{run_tag}"

    # 2. Push thêm mới (Insert) theo thứ tự bảng cha -> con + Vector 192 chiều
    valid_vec = [0.05] * 192
    r_push = requests.post(
        f"{API_V1}/sync/push",
        json={
            "students": [
                {
                    "student_id": stu_id,
                    "full_name": "Nguyen Van Dong Bo",
                    "email": f"{stu_id.lower()}@hkdn.edu.vn",
                    "face_embedding": valid_vec,
                    "uuid": stu_uuid,
                    "updated_at": "2026-11-10T08:00:00Z",
                    "deleted_at": None,
                }
            ],
            "subjects": [
                {
                    "subject_id": sub_id,
                    "subject_name": "He Phan Tan & Dong Bo Du Lieu",
                    "uuid": sub_uuid,
                    "updated_at": "2026-11-10T08:00:00Z",
                    "deleted_at": None,
                }
            ],
            "enrollments": [
                {
                    "student_id": stu_id,
                    "subject_id": sub_id,
                    "enrollment_status": "Enrolled",
                    "uuid": enr_uuid,
                    "updated_at": "2026-11-10T08:00:00Z",
                    "deleted_at": None,
                }
            ],
        },
        timeout=5,
    )
    assert r_push.status_code == 200
    p_data = r_push.json()
    assert p_data["applied"]["students"] == 1 and p_data["applied"]["subjects"] == 1
    print(f"[2] Push thêm mới (Insert + Vector 192 chiều)      : OK (latest_seq tăng lên {p_data['latest_seq']})")

    # 3. Kiểm tra chiến lược Last-Write-Wins (LWW): gửi bản ghi có updated_at cũ hơn -> phải bị skipped
    r_lww = requests.post(
        f"{API_V1}/sync/push",
        json={
            "students": [
                {
                    "student_id": stu_id,
                    "full_name": "Ten CuBiBoQua",
                    "uuid": stu_uuid,
                    "updated_at": "2026-11-10T07:00:00Z",
                }
            ]
        },
        timeout=5,
    )
    assert r_lww.status_code == 200 and r_lww.json()["skipped"]["students"] == 1
    print("[3] Giải quyết xung đột Last-Write-Wins (LWW)      : OK (Bản ghi cũ hơn tự động đưa vào skipped)")

    # 4. Push Xóa mềm (Soft Delete: deleted_at != null) với updated_at mới hơn
    r_del = requests.post(
        f"{API_V1}/sync/push",
        json={
            "students": [
                {
                    "student_id": stu_id,
                    "full_name": "Nguyen Van Dong Bo (Da Xoa Mem)",
                    "uuid": stu_uuid,
                    "updated_at": "2026-11-10T09:00:00Z",
                    "deleted_at": "2026-11-10T09:00:00Z",
                }
            ]
        },
        timeout=5,
    )
    assert r_del.status_code == 200 and r_del.json()["applied"]["students"] == 1
    print("[4] Push Xóa mềm (Soft Delete - deleted_at != null): OK (Đã cập nhật trạng thái xóa mềm)")

    # 5. Pull thay đổi về qua after_seq
    r_pull = requests.get(f"{API_V1}/sync/pull?after_seq={base_seq}&limit=100", timeout=5)
    assert r_pull.status_code == 200
    pull_json = r_pull.json()
    matched = [s for s in pull_json["changes"]["students"] if s["student_id"] == stu_id]
    assert len(matched) == 1 and matched[0]["deleted_at"] is not None
    print(f"[5] Pull theo after_seq={base_seq} (Bao gồm bản ghi xóa mềm): OK (next_seq={pull_json['next_seq']}, has_more={pull_json['has_more']})")

    # 6. Kiểm tra tương thích Hợp đồng Android SyncManager (Outbox List + since_seq)
    outbox_uuid = str(uuid.uuid4())
    r_android_push = requests.post(
        f"{API_V1}/sync/push",
        json={
            "device_id": "android_tablet_01",
            "client_timestamp": 1794300000000,
            "changes": [
                {
                    "change_id": f"outbox_chg_{run_tag}",
                    "uuid": outbox_uuid,
                    "table_name": "checkin_history",
                    "operation": "INSERT",
                    "payload": {
                        "student_id": stu_id,
                        "subject_id": sub_id,
                        "checkin_time": "08:30:00",
                        "checkin_date": "2026-11-10",
                    },
                    "updated_at": 1794300000000,
                }
            ],
        },
        timeout=5,
    )
    assert r_android_push.status_code == 200
    ap_data = r_android_push.json()
    assert ap_data["success"] is True and f"outbox_chg_{run_tag}" in ap_data["synced_change_ids"]
    print(f"[6] Push định dạng Outbox Android (SyncPushRequest): OK (synced_change_ids=['outbox_chg_{run_tag}'])")

    r_android_pull = requests.get(f"{API_V1}/sync/pull?since_seq={base_seq}&limit=50", timeout=5)
    assert r_android_pull.status_code == 200
    apull_data = r_android_pull.json()
    assert isinstance(apull_data["changes"], list) and apull_data["new_seq"] >= pull_json["next_seq"]
    print(f"[7] Pull định dạng Android (since_seq -> new_seq)  : OK (Nhận {len(apull_data['changes'])} SyncChange items, new_seq={apull_data['new_seq']})")

    # 7. Kiểm tra bắt lỗi Khóa ngoại (409) & Sai chiều Vector (422)
    r_fk = requests.post(
        f"{API_V1}/sync/push",
        json={"enrollments": [{"student_id": "NO_STU_999", "subject_id": "NO_SUB_999"}]},
        timeout=5,
    )
    assert r_fk.status_code == 409

    r_vec = requests.post(
        f"{API_V1}/sync/push",
        json={"students": [{"student_id": "BAD_VEC", "face_embedding": [0.1, 0.2]}]},
        timeout=5,
    )
    assert r_vec.status_code == 422
    print("[8] Kiểm tra chặn lỗi FK (409) & Vector != 192 (422): OK")

    print("=" * 75)
    print(" -> HOÀN TẤT KIỂM TRA GIAI ĐOẠN 5 PHÍA SERVER THÀNH CÔNG 100%!")
    print("=" * 75)


if __name__ == "__main__":
    run_phase5_sync_check()

