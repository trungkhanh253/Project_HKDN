"""Test đồng bộ chuyên sâu theo docs/openapi.yml (bổ sung cho test_sync_api.py của nhóm Server).

Mỗi test tự sinh uuid/mã ngẫu nhiên và chỉ xét thay đổi sau mốc `cursor`,
nên chạy lại nhiều lần không bị trùng. Dữ liệu mẫu được ghi vào DB mà API đang dùng.
"""
import io
import time
import pytest

from sync_helpers import (TABLES, flatten, iso, latest_seq, new_code, new_sid, new_uuid,
                          auth_headers, pull, pull_all, push, rows, student, subject)

pytestmark = pytest.mark.api


@pytest.fixture(scope="module")
def hdr(api, v1):
    return auth_headers(api, v1)


@pytest.fixture
def cursor(api, v1, hdr):
    return latest_seq(api, v1, hdr)


# ---------- pull ----------
def test_pull_shape_and_global_seq(api, v1, hdr, cursor):
    code = new_code()
    r = push(api, v1, hdr, {"subjects": [subject(code)],
                            "students": [student(new_sid()), student(new_sid())]})
    assert r.status_code == 200
    body = pull(api, v1, hdr, cursor).json()
    assert {"after_seq", "next_seq", "latest_seq", "limit", "has_more", "changes"} <= set(body)
    assert set(body["changes"]) == set(TABLES)
    flat = flatten(body)
    seqs = [rec["seq"] for _, rec in flat]
    assert len(flat) >= 3
    assert len(seqs) == len(set(seqs)), "seq phải duy nhất giữa các bảng (sequence dùng chung)"
    assert body["next_seq"] == max(seqs)


def test_pull_after_latest_is_empty(api, v1, hdr, cursor):
    body = pull(api, v1, hdr, cursor).json()
    assert flatten(body) == []
    assert body["has_more"] is False
    assert body["next_seq"] == cursor


def test_pull_pagination_across_tables(api, v1, hdr, cursor):
    code, ids = new_code(), [new_sid() for _ in range(3)]
    r = push(api, v1, hdr, {"subjects": [subject(code)], "students": [student(i) for i in ids]})
    assert r.status_code == 200
    seen, since, pages = [], cursor, 0
    while True:
        page = pull(api, v1, hdr, since, limit=2).json()
        flat = flatten(page)
        assert len(flat) <= 2, "mỗi trang không được vượt limit"
        seen += flat
        since, pages = page["next_seq"], pages + 1
        if not page["has_more"]:
            break
        assert pages < 100
    seqs = [rec["seq"] for _, rec in seen]
    assert pages >= 2
    assert seqs == sorted(set(seqs)), "các trang không được trùng hoặc lùi seq"
    got = {s["student_id"] for s in rows(seen, "students")}
    assert set(ids) <= got


def test_pull_invalid_param_returns_400(api, v1, hdr):
    r = api.get(f"{v1}/sync/pull", params={"after_seq": "abc"}, headers=hdr, timeout=10)
    assert r.status_code == 400
    assert "error" in r.json()


# ---------- push: thêm, sửa, xóa, xung đột ----------
def test_push_twice_does_not_duplicate(api, v1, hdr, cursor):
    s, u, ts = new_sid(), new_uuid(), iso()
    for _ in range(2):
        assert push(api, v1, hdr, {"students": [student(s, u, ts=ts)]}).status_code == 200
    recs, _ = pull_all(api, v1, hdr, cursor)
    assert len(rows(recs, "students", student_id=s)) == 1


def test_update_bumps_seq_and_is_pulled(api, v1, hdr):
    s, u = new_sid(), new_uuid()
    r1 = push(api, v1, hdr, {"students": [student(s, u, name="Ten Cu", ts=iso(0))]})
    assert r1.status_code == 200
    seq1 = r1.json()["latest_seq"]
    r2 = push(api, v1, hdr, {"students": [student(s, u, name="Ten Moi", ts=iso(10))]})
    assert r2.json()["applied"]["students"] == 1
    recs, _ = pull_all(api, v1, hdr, seq1)
    mine = rows(recs, "students", uuid=u)
    assert mine, "UPDATE không xuất hiện khi pull: seq không tăng?"
    assert mine[-1]["full_name"] == "Ten Moi" and mine[-1]["seq"] > seq1


def test_soft_delete_is_pulled_with_deleted_at(api, v1, hdr):
    s, u = new_sid(), new_uuid()
    r1 = push(api, v1, hdr, {"students": [student(s, u, ts=iso(0))]})
    seq1 = r1.json()["latest_seq"]
    r2 = push(api, v1, hdr, {"students": [student(s, u, ts=iso(10), deleted_at=iso(10))]})
    assert r2.status_code == 200
    recs, _ = pull_all(api, v1, hdr, seq1)
    mine = rows(recs, "students", uuid=u)
    assert mine and mine[-1]["deleted_at"] is not None


def test_older_update_is_skipped_and_keeps_newer(api, v1, hdr, cursor):
    s, u = new_sid(), new_uuid()
    push(api, v1, hdr, {"students": [student(s, u, name="Ban Moi", ts=iso(60))]})
    r = push(api, v1, hdr, {"students": [student(s, u, name="Ban Cu", ts=iso(0))]})
    assert r.status_code == 200
    assert r.json()["skipped"]["students"] == 1 and r.json()["applied"]["students"] == 0
    recs, _ = pull_all(api, v1, hdr, cursor)
    assert rows(recs, "students", uuid=u)[-1]["full_name"] == "Ban Moi"


def test_same_student_id_from_two_devices_is_merged_into_one_row(api, v1, hdr, cursor):
    s, u1, u2 = new_sid(), new_uuid(), new_uuid()
    push(api, v1, hdr, {"students": [student(s, u1, name="May A", ts=iso(0))]})
    push(api, v1, hdr, {"students": [student(s, u2, name="May B", ts=iso(10))]})
    recs, _ = pull_all(api, v1, hdr, cursor)
    found = rows(recs, "students", student_id=s)
    assert len(found) == 1 and found[0]["full_name"] == "May B"


@pytest.mark.xfail(strict=False, reason=(
    "Khi gộp theo mã sinh viên, _apply_fields ghi đè uuid của bản ghi cũ bằng uuid máy sau; "
    "máy đầu mất liên kết. Cần Lead chốt: giữ uuid nào làm chuẩn."))
def test_merge_keeps_first_uuid(api, v1, hdr, cursor):
    s, u1, u2 = new_sid(), new_uuid(), new_uuid()
    push(api, v1, hdr, {"students": [student(s, u1, name="May A", ts=iso(0))]})
    push(api, v1, hdr, {"students": [student(s, u2, name="May B", ts=iso(10))]})
    recs, _ = pull_all(api, v1, hdr, cursor)
    assert rows(recs, "students", student_id=s)[0]["uuid"] == u1


# ---------- push: dữ liệu sai ----------
def test_fk_error_returns_409_and_rolls_back_whole_batch(api, v1, hdr, cursor):
    s = new_sid()
    body = {"students": [student(s)],
            "enrollments": [{"student_id": s, "subject_id": new_code("NOSUCH"),
                             "enrollment_status": "Enrolled", "uuid": new_uuid(),
                             "updated_at": iso()}]}
    r = push(api, v1, hdr, body)
    assert r.status_code == 409
    err = r.json()["error"]
    assert "code" in err and "message" in err
    recs, _ = pull_all(api, v1, hdr, cursor)
    assert not rows(recs, "students", student_id=s), \
        "push lỗi phải hoàn tác cả gói (all-or-nothing)"


def test_push_bad_timestamp_returns_4xx_json(api, v1, hdr):
    bad = {**student(new_sid()), "updated_at": "khong-phai-ngay"}
    r = push(api, v1, hdr, {"students": [bad]})
    assert r.status_code in (400, 422), f"HTTP {r.status_code}: {r.text[:150]}"
    assert "error" in r.json()


def test_unknown_route_returns_json_error(api, v1):
    r = api.get(f"{v1}/khong-co-route", timeout=5)
    assert r.status_code == 404
    assert "application/json" in r.headers.get("Content-Type", ""), \
        "openapi.yml hứa mọi lỗi đều là JSON {error:{code,message}}"
    assert "error" in r.json()


def test_old_format_body_is_rejected_not_silently_ignored(api, v1, hdr):
    """Body theo ví dụ JSON cũ của Lead ({device_id, changes:[...]}) không được trả 200 rồi bỏ qua dữ liệu."""
    body = {"device_id": "x", "changes": [{
        "table": "students", "uuid": new_uuid(), "operation": "INSERT",
        "updated_at": int(time.time() * 1000),
        "data": {"student_id": new_sid(), "full_name": "X"}}]}
    r = push(api, v1, hdr, body)
    assert r.status_code in (400, 422), \
        f"HTTP {r.status_code}: server nhận 'thành công' nhưng không áp dụng dữ liệu nào"


def test_checkin_with_foreign_checkin_id_does_not_overwrite_other_record(api, v1, hdr, cursor):
    """Hai máy cùng có checkin_id=N (SQLite tự tăng ở mỗi máy) nhưng uuid khác nhau
    thì phải là hai bản ghi riêng."""
    code, s1, s2, c1, c2 = new_code(), new_sid(), new_sid(), new_uuid(), new_uuid()
    assert push(api, v1, hdr, {"subjects": [subject(code)],
                               "students": [student(s1), student(s2)]}).status_code == 200
    rec = lambda stu, u, ts, **x: {"student_id": stu, "subject_id": code, "checkin_time": "07:00:00",
                                   "checkin_date": "2026-11-09", "uuid": u, "updated_at": ts, **x}
    assert push(api, v1, hdr, {"checkin_history": [rec(s1, c1, iso(0))]}).status_code == 200
    recs, _ = pull_all(api, v1, hdr, cursor)
    n = rows(recs, "checkin_history", uuid=c1)[0]["checkin_id"]
    assert push(api, v1, hdr, {"checkin_history": [rec(s2, c2, iso(10), checkin_id=n)]}).status_code == 200
    recs, _ = pull_all(api, v1, hdr, cursor)
    uuids = {r["uuid"] for r in rows(recs, "checkin_history")}
    assert {c1, c2} <= uuids, "bản ghi điểm danh của máy A đã bị bản của máy B ghi đè"


# ---------- import CSV rồi đồng bộ về ----------
def test_import_csv_then_pull(api, v1, hdr, cursor):
    good, bad = new_sid(), new_sid()
    csv_text = f"student_id,full_name,class_name\n{good},Import Test,CLS01\n{bad},,CLS01\n"
    r = api.post(f"{v1}/import/csv",
                 files={"file": ("s.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
                 data={"type": "students"}, headers=hdr, timeout=10)
    assert r.status_code == 202
    job_id, job = r.json()["job_id"], {}
    for _ in range(30):
        job = api.get(f"{v1}/jobs/{job_id}", headers=hdr, timeout=5).json()
        if job.get("status") in ("finished", "failed"):
            break
        time.sleep(1)
    assert job.get("status") == "finished", f"job: {job}"
    res = job["result"]
    assert res["imported"] == 1 and res["skipped"] == 1 and len(res["errors"]) == 1
    recs, _ = pull_all(api, v1, hdr, cursor)
    ids = {s["student_id"] for s in rows(recs, "students")}
    assert good in ids and bad not in ids
