"""Test đồng bộ theo ví dụ JSON của Lead:
   POST /api/v1/auth/login, POST /api/v1/sync/push, GET /api/v1/sync/pull?since=&limit=

Cần tài khoản admin để test: đặt TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD trong .env.
CHÚ Ý: test ghi dữ liệu mẫu (student_id bắt đầu bằng "T" + 8 ký tự hex) vào DB mà API đang dùng.
Mỗi test tự tạo dữ liệu mới (uuid, student_id ngẫu nhiên) nên chạy lại nhiều lần không trùng.
"""
import io
import os
import time
import uuid

import pytest

pytestmark = pytest.mark.api

PULL_PARAM = os.getenv("TEST_PULL_PARAM", "since")  # ví dụ của Lead dùng "since"; tài liệu cũ ghi after_seq


# ---------------- helper ----------------
def _now_ms():
    return int(time.time() * 1000)


def _sid():
    return "T" + uuid.uuid4().hex[:8].upper()


def _student(sid, u=None, op="INSERT", name="Nguyen Van A", ts=None):
    ch = {"table": "students", "uuid": u or str(uuid.uuid4()),
          "operation": op, "updated_at": ts or _now_ms()}
    if op != "DELETE":
        # Trường theo ví dụ của Lead + class_name (cột NOT NULL của bảng student thật)
        ch["data"] = {"student_id": sid, "full_name": name, "class_name": "CLS01",
                      "email": "t@example.com", "phone": "0900000001"}
    return ch


def _push(api, v1, auth, changes, device="test-device-1"):
    return api.post(f"{v1}/sync/push", json={"device_id": device, "changes": changes},
                    headers=auth, timeout=15)


def _pull(api, v1, auth, since, limit=500):
    return api.get(f"{v1}/sync/pull", params={PULL_PARAM: since, "limit": limit},
                   headers=auth, timeout=15)


def _pull_all(api, v1, auth, since=0, limit=500):
    """Kéo hết các trang; trả về (danh sách changes, next_seq cuối)."""
    changes, cur = [], since
    for _ in range(1000):
        r = _pull(api, v1, auth, cur, limit)
        assert r.status_code == 200, f"pull lỗi HTTP {r.status_code}"
        body = r.json()
        changes += body["changes"]
        cur = body["next_seq"]
        if not body["has_more"]:
            return changes, cur
    raise AssertionError("pull không kết thúc (has_more luôn True)")


def _mine(changes, *uuids):
    return [c for c in changes if c["uuid"] in uuids]


def _data(c):
    return c.get("data") or {}


@pytest.fixture
def cursor(api, v1, auth):
    """seq mới nhất tại thời điểm bắt đầu test; chỉ xét thay đổi sau mốc này."""
    return _pull_all(api, v1, auth, 0)[1]


# ---------------- đăng nhập ----------------
def test_login_returns_tokens(api, v1):
    email, pw = os.getenv("TEST_ADMIN_EMAIL"), os.getenv("TEST_ADMIN_PASSWORD")
    if not email or not pw:
        pytest.skip("Chưa đặt TEST_ADMIN_EMAIL / TEST_ADMIN_PASSWORD")
    r = api.post(f"{v1}/auth/login", json={"email": email, "password": pw}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body.get("access_token") and body.get("refresh_token")


def test_login_wrong_password_rejected(api, v1):
    r = api.post(f"{v1}/auth/login",
                 json={"email": "nobody@example.com", "password": "wrong"}, timeout=10)
    assert r.status_code in (400, 401)
    assert "error" in r.json()


@pytest.mark.parametrize("method,path", [("post", "/sync/push"), ("get", "/sync/pull")])
def test_sync_requires_token(api, v1, method, path):
    r = getattr(api, method)(f"{v1}{path}", timeout=5)
    assert r.status_code in (401, 422)


# ---------------- push và pull cơ bản ----------------
def test_insert_then_pull_returns_record(api, v1, auth, cursor):
    sid, u = _sid(), str(uuid.uuid4())
    r = _push(api, v1, auth, [_student(sid, u)])
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert res["uuid"] == u and res["status"] == "ok"

    changes, _ = _pull_all(api, v1, auth, cursor)
    mine = _mine(changes, u)
    assert mine, "pull không trả bản ghi vừa push"
    last = mine[-1]
    assert last["table"] == "students" and last["operation"] == "UPSERT"
    assert _data(last)["student_id"] == sid


def test_pull_response_shape_and_order(api, v1, auth, cursor):
    _push(api, v1, auth, [_student(_sid()), _student(_sid())])
    body = _pull(api, v1, auth, cursor).json()
    assert {"changes", "next_seq", "has_more"} <= set(body)
    for c in body["changes"]:
        assert {"table", "uuid", "seq", "operation", "updated_at"} <= set(c)
        assert c["operation"] in ("UPSERT", "DELETE")
        assert isinstance(c["updated_at"], int)  # mili giây
    seqs = [c["seq"] for c in body["changes"]]
    assert seqs == sorted(set(seqs)), "seq phải tăng dần và không trùng"
    if seqs:
        assert body["next_seq"] == seqs[-1]


def test_pull_after_latest_is_empty(api, v1, auth, cursor):
    body = _pull(api, v1, auth, cursor).json()
    assert body["changes"] == []
    assert body["has_more"] is False
    assert body["next_seq"] >= cursor  # con trỏ không được lùi


def test_pull_pagination(api, v1, auth, cursor):
    us = [str(uuid.uuid4()) for _ in range(3)]
    _push(api, v1, auth, [_student(_sid(), u) for u in us])
    first = _pull(api, v1, auth, cursor, limit=2).json()
    assert len(first["changes"]) == 2 and first["has_more"] is True
    second = _pull(api, v1, auth, first["next_seq"], limit=2).json()
    both = first["changes"] + second["changes"]
    seqs = [c["seq"] for c in both]
    assert seqs == sorted(set(seqs)), "các trang không được trùng hoặc lùi seq"
    assert set(us) <= {c["uuid"] for c in both} | {c["uuid"] for c in
            _pull_all(api, v1, auth, second["next_seq"])[0]}


# ---------------- chống trùng, sửa, xóa ----------------
def test_push_twice_does_not_duplicate(api, v1, auth, cursor):
    sid, u = _sid(), str(uuid.uuid4())
    for _ in range(2):
        r = _push(api, v1, auth, [_student(sid, u)])
        assert r.status_code == 200
        assert r.json()["results"][0]["status"] in ("ok", "conflict")
    changes, _ = _pull_all(api, v1, auth, cursor)
    uuids = {c["uuid"] for c in changes if _data(c).get("student_id") == sid}
    assert uuids == {u}


def test_update_gets_new_seq_and_is_pulled(api, v1, auth, cursor):
    """Kiểm tra ở mức API điều mà test DB chỉ ghi nhận là xfail (seq tăng khi UPDATE)."""
    sid, u, t = _sid(), str(uuid.uuid4()), _now_ms()
    _push(api, v1, auth, [_student(sid, u, name="Ten Cu", ts=t)])
    _, s1 = _pull_all(api, v1, auth, cursor)
    r = _push(api, v1, auth, [_student(sid, u, op="UPDATE", name="Ten Moi", ts=t + 1000)])
    assert r.json()["results"][0]["status"] == "ok"
    changes, _ = _pull_all(api, v1, auth, s1)
    mine = _mine(changes, u)
    assert mine, "UPDATE không xuất hiện khi pull: seq không tăng?"
    assert mine[-1]["seq"] > s1 and _data(mine[-1])["full_name"] == "Ten Moi"


def test_delete_is_pulled_as_delete(api, v1, auth, cursor):
    sid, u, t = _sid(), str(uuid.uuid4()), _now_ms()
    _push(api, v1, auth, [_student(sid, u, ts=t)])
    r = _push(api, v1, auth, [_student(sid, u, op="DELETE", ts=t + 1000)])
    assert r.json()["results"][0]["status"] == "ok"
    changes, _ = _pull_all(api, v1, auth, cursor)
    assert _mine(changes, u)[-1]["operation"] == "DELETE"


def test_older_update_is_conflict_and_keeps_newer(api, v1, auth, cursor):
    sid, u, t = _sid(), str(uuid.uuid4()), _now_ms()
    _push(api, v1, auth, [_student(sid, u, name="Ban Moi", ts=t + 60000)])
    r = _push(api, v1, auth, [_student(sid, u, op="UPDATE", name="Ban Cu", ts=t)])
    assert r.json()["results"][0]["status"] == "conflict"
    changes, _ = _pull_all(api, v1, auth, cursor)
    assert _data(_mine(changes, u)[-1])["full_name"] == "Ban Moi"


def test_same_student_id_from_two_devices_is_merged(api, v1, auth, cursor):
    """Kế hoạch 2.2: cùng Mã sinh viên từ 2 máy thì gộp, bản mới hơn thắng.
    GIẢ ĐỊNH cách quan sát (cần Người 3 xác nhận): chỉ còn đúng 1 uuid còn sống."""
    sid, u1, u2, t = _sid(), str(uuid.uuid4()), str(uuid.uuid4()), _now_ms()
    _push(api, v1, auth, [_student(sid, u1, name="May A", ts=t)], device="dev-A")
    _push(api, v1, auth, [_student(sid, u2, name="May B", ts=t + 1000)], device="dev-B")
    changes, _ = _pull_all(api, v1, auth, cursor)
    latest = {}
    for c in sorted(changes, key=lambda x: x["seq"]):
        if c["uuid"] in (u1, u2) or _data(c).get("student_id") == sid:
            latest[c["uuid"]] = c
    alive = [c for c in latest.values() if c["operation"] != "DELETE"]
    assert len(alive) == 1, f"Có {len(alive)} bản ghi sống cho cùng một student_id"
    assert _data(alive[0])["full_name"] == "May B"


# ---------------- dữ liệu sai ----------------
def test_enrollment_without_student_is_not_accepted(api, v1, auth):
    ch = {"table": "enrollments", "uuid": str(uuid.uuid4()), "operation": "INSERT",
          "updated_at": _now_ms(),
          "data": {"student_id": "NO_" + _sid(), "subject_id": "NO_SUCH",
                   "enrollment_status": "Enrolled"}}
    r = _push(api, v1, auth, [ch])
    assert r.status_code < 500
    if r.status_code == 200:
        assert r.json()["results"][0]["status"] != "ok"


def test_push_malformed_body_returns_400(api, v1, auth):
    r = api.post(f"{v1}/sync/push", json={"device_id": "x"}, headers=auth, timeout=10)
    assert r.status_code == 400
    assert "error" in r.json()


@pytest.mark.parametrize("patch", [{"table": "no_such_table"}, {"operation": "BOGUS"}])
def test_bad_table_or_operation_not_accepted(api, v1, auth, patch):
    ch = {**_student(_sid()), **patch}
    r = _push(api, v1, auth, [ch])
    assert r.status_code < 500
    if r.status_code == 200:
        assert r.json()["results"][0]["status"] != "ok"


# ---------------- import CSV rồi đồng bộ về ----------------
def test_imported_students_are_pullable(api, v1, auth, cursor):
    sid = _sid()
    csv = f"student_id,full_name,class_name\n{sid},Import Test,CLS01\n"
    r = api.post(f"{v1}/import/csv",
                 files={"file": ("s.csv", io.BytesIO(csv.encode()), "text/csv")},
                 headers=auth, timeout=10)
    assert r.status_code == 202
    job_id, status = r.json()["job_id"], None
    for _ in range(30):
        status = api.get(f"{v1}/jobs/{job_id}", headers=auth, timeout=5).json().get("status")
        if status in ("finished", "failed"):
            break
        time.sleep(1)
    assert status == "finished"
    changes, _ = _pull_all(api, v1, auth, cursor)
    assert any(_data(c).get("student_id") == sid for c in changes), \
        "Sinh viên import xong phải xuất hiện khi pull (kế hoạch giai đoạn 6)"


# ---------------- ví dụ nguyên văn của Lead ----------------
@pytest.mark.xfail(strict=False, reason=(
    "Ví dụ của Lead gửi email/phone (DB student chưa có) và thiếu class_name (NOT NULL trong DB). "
    "Enrollment dùng subject_id/enrollment_status, DB dùng subject_code, không có cột status."))
def test_spec_example_payload_is_accepted_as_is(api, v1, auth):
    ch = {"table": "students", "uuid": str(uuid.uuid4()), "operation": "INSERT",
          "updated_at": _now_ms(),
          "data": {"student_id": _sid(), "full_name": "Nguyen Van An",
                   "email": "an@example.com", "phone": "0900000001"}}
    r = _push(api, v1, auth, [ch])
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "ok"
