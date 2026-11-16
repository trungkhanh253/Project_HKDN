"""Test cho GET /checkins, DELETE /checkins/{id}, GET /subjects/{id}/attendance-summary.

Viết theo kiểu test của project: gọi API đang chạy qua HTTP (fixture api, v1 trong conftest.py).
Không cần TEST_DATABASE_URL. Dữ liệu mẫu tạo bằng /sync/push với mã ngẫu nhiên cho mỗi lần chạy,
cuối mỗi test được xóa mềm (deleted_at) nên không ảnh hưởng dữ liệu demo.

Chạy:  docker compose exec api python -m pytest tests/test_checkins.py -q
Tài khoản: SUPER_ADMIN lấy từ TEST_ADMIN_EMAIL/PASSWORD (mặc định admin@hkdn.edu.vn),
giảng viên lấy từ TEST_LECTURER_EMAIL/PASSWORD (mặc định lecturer@hkdn.edu.vn / lecturer123).
"""
import os
from types import SimpleNamespace

import pytest

try:
    from sync_helpers import creds, iso, new_code, new_sid, new_uuid, pull_all, push, rows
except ImportError:  # chạy từ thư mục khác
    from tests.sync_helpers import creds, iso, new_code, new_sid, new_uuid, pull_all, push, rows

pytestmark = pytest.mark.api

D1, D2, D3 = "2026-11-02", "2026-11-03", "2026-11-04"


def _login(api, v1, email, password):
    r = api.post(f"{v1}/auth/login", json={"email": email, "password": password}, timeout=10)
    if r.status_code != 200:
        pytest.skip(f"Không đăng nhập được {email} (HTTP {r.status_code}); kiểm tra seed_admin.py")
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["admin"]["admin_id"]


@pytest.fixture(scope="session")
def super_ctx(api, v1):
    email, password = creds()
    headers, admin_id = _login(api, v1, email, password)
    return SimpleNamespace(h=headers, admin_id=admin_id)


@pytest.fixture(scope="session")
def lecturer_ctx(api, v1):
    headers, admin_id = _login(api, v1,
                               os.getenv("TEST_LECTURER_EMAIL", "lecturer@hkdn.edu.vn"),
                               os.getenv("TEST_LECTURER_PASSWORD", "lecturer123"))
    return SimpleNamespace(h=headers, admin_id=admin_id)


def _checkin(student_id, subject_id, day, hms="07:30:00", deleted_at=None, u=None, ts=None):
    return {"student_id": student_id, "subject_id": subject_id, "checkin_date": day, "checkin_time": hms,
            "uuid": u or new_uuid(), "updated_at": ts or iso(-60), "deleted_at": deleted_at}


@pytest.fixture()
def seeded(api, v1, super_ctx, lecturer_ctx):
    """s1 (giảng viên): a điểm danh 3 ngày (D1, D2, D3); b ngày D1 và HAI lần ngày D3; c chưa lần nào.
    s2 (super admin): chỉ a điểm danh ngày D2."""
    a, b, c = new_sid(), new_sid(), new_sid()
    s1, s2 = new_code("ZT"), new_code("ZT")
    names = {a: f"ZT {a}", b: f"ZT {b}", c: f"ZT {c}"}
    stu_uuid = {sid: new_uuid() for sid in (a, b, c)}
    sub_uuid = {s1: new_uuid(), s2: new_uuid()}
    checkins = (
        [_checkin(a, s1, d) for d in (D1, D2, D3)]
        + [_checkin(b, s1, D1), _checkin(b, s1, D3, "07:30:00"), _checkin(b, s1, D3, "09:10:00")]
        + [_checkin(a, s2, D2)]
    )
    enr = [(a, s1), (b, s1), (c, s1), (a, s2)]
    enr_uuid = {key: new_uuid() for key in enr}

    def subject_row(code, instructor, deleted_at=None):
        return {"subject_id": code, "subject_name": f"ZT {code}", "instructor_id": instructor, "created_by": super_ctx.admin_id,
                "uuid": sub_uuid[code], "updated_at": iso(-60) if not deleted_at else iso(), "deleted_at": deleted_at}

    def student_row(sid, deleted_at=None):
        return {"student_id": sid, "full_name": names[sid], "email": "zt@example.com", "uuid": stu_uuid[sid],
                "updated_at": iso(-60) if not deleted_at else iso(), "deleted_at": deleted_at}

    def enr_row(key, deleted_at=None):
        return {"student_id": key[0], "subject_id": key[1], "enrollment_status": "Enrolled", "uuid": enr_uuid[key],
                "updated_at": iso(-60) if not deleted_at else iso(), "deleted_at": deleted_at}

    body = {
        "students": [student_row(sid) for sid in (a, b, c)],
        "subjects": [subject_row(s1, lecturer_ctx.admin_id), subject_row(s2, super_ctx.admin_id)],
        "enrollments": [enr_row(key) for key in enr],
        "checkin_history": checkins,
    }
    r = push(api, v1, super_ctx.h, body)
    assert r.status_code == 200, f"push dữ liệu mẫu lỗi: HTTP {r.status_code} {r.text[:300]}"
    applied = r.json()["applied"]
    assert applied["checkin_history"] == len(checkins), f"push checkin_history chưa nhận đủ: {r.text[:300]}"

    yield SimpleNamespace(a=a, b=b, c=c, s1=s1, s2=s2, names=names, n_s1=6, n_s2=1)

    stamp = iso()
    cleanup = {
        "checkin_history": [{**ck, "deleted_at": stamp, "updated_at": stamp} for ck in checkins],
        "enrollments": [enr_row(key, stamp) for key in enr],
        "subjects": [subject_row(s1, lecturer_ctx.admin_id, stamp), subject_row(s2, super_ctx.admin_id, stamp)],
        "students": [student_row(sid, stamp) for sid in (a, b, c)],
    }
    push(api, v1, super_ctx.h, cleanup)


def _get(api, v1, headers, path, **params):
    return api.get(f"{v1}{path}", params=params or None, headers=headers, timeout=15)


# ------------------------------------------------------------------ GET /checkins
def test_requires_token(api, v1):
    assert api.get(f"{v1}/checkins", timeout=10).status_code == 401


def test_list_shape_filters_and_paging(api, v1, super_ctx, seeded):
    body = _get(api, v1, super_ctx.h, "/checkins", limit=5).json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["limit"] == 5 and body["offset"] == 0 and body["total"] >= 7
    assert {"checkin_id", "student_id", "subject_id", "student_name", "checkin_date", "checkin_time", "uuid", "seq"} <= set(body["items"][0])

    assert _get(api, v1, super_ctx.h, "/checkins", subject_id=seeded.s1).json()["total"] == seeded.n_s1
    by_student = _get(api, v1, super_ctx.h, "/checkins", subject_id=seeded.s1, student_id=seeded.b).json()
    assert by_student["total"] == 3 and all(i["student_name"] == seeded.names[seeded.b] for i in by_student["items"])
    by_date = _get(api, v1, super_ctx.h, "/checkins", subject_id=seeded.s1, date_from=D2, date_to=D3).json()
    assert by_date["total"] == 4

    page1 = _get(api, v1, super_ctx.h, "/checkins", subject_id=seeded.s1, limit=4, offset=0).json()
    page2 = _get(api, v1, super_ctx.h, "/checkins", subject_id=seeded.s1, limit=4, offset=4).json()
    ids = [i["checkin_id"] for i in page1["items"] + page2["items"]]
    assert page1["total"] == page2["total"] == seeded.n_s1 and len(ids) == 6 and len(set(ids)) == 6
    dates = [i["checkin_date"] for i in page1["items"]]
    assert dates == sorted(dates, reverse=True)           # mặc định -checkin_date


@pytest.mark.parametrize("params", [
    {"date_from": "11/02/2026"},
    {"date_from": "2026-11-05", "date_to": "2026-11-01"},
    {"limit": "abc"},
    {"sort": "password"},
])
def test_list_invalid_params_422(api, v1, super_ctx, params):
    r = _get(api, v1, super_ctx.h, "/checkins", **params)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_lecturer_scope(api, v1, lecturer_ctx, seeded):
    items = _get(api, v1, lecturer_ctx.h, "/checkins", limit=500).json()["items"]
    assert all(i["subject_id"] != seeded.s2 for i in items)                 # không thấy môn của người khác
    assert _get(api, v1, lecturer_ctx.h, "/checkins", subject_id=seeded.s1).json()["total"] == seeded.n_s1
    r = _get(api, v1, lecturer_ctx.h, "/checkins", subject_id=seeded.s2)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


# ------------------------------------------------------------------ DELETE /checkins/{id}
def _first_item(api, v1, headers, subject_id):
    return _get(api, v1, headers, "/checkins", subject_id=subject_id).json()["items"][0]


def test_delete_is_soft_and_synced(api, v1, super_ctx, lecturer_ctx, seeded):
    item = _first_item(api, v1, lecturer_ctx.h, seeded.s1)
    cid, uid, seq_before = item["checkin_id"], item["uuid"], item["seq"]

    assert api.delete(f"{v1}/checkins/{cid}", headers=lecturer_ctx.h, timeout=10).status_code == 204
    after = _get(api, v1, lecturer_ctx.h, "/checkins", subject_id=seeded.s1).json()
    assert after["total"] == seeded.n_s1 - 1 and cid not in [i["checkin_id"] for i in after["items"]]
    assert api.delete(f"{v1}/checkins/{cid}", headers=lecturer_ctx.h, timeout=10).status_code == 404   # đã xóa mềm

    records, _ = pull_all(api, v1, super_ctx.h, after_seq=seq_before - 1)       # máy khác kéo về vẫn thấy bản xóa
    found = rows(records, "checkin_history", uuid=uid)
    assert len(found) == 1 and found[0]["deleted_at"] is not None and found[0]["seq"] > seq_before


def test_delete_forbidden_and_not_found(api, v1, super_ctx, lecturer_ctx, seeded):
    other = _first_item(api, v1, super_ctx.h, seeded.s2)["checkin_id"]
    assert api.delete(f"{v1}/checkins/{other}", headers=lecturer_ctx.h, timeout=10).status_code == 403
    assert api.delete(f"{v1}/checkins/999999999", headers=lecturer_ctx.h, timeout=10).status_code == 404
    assert api.delete(f"{v1}/checkins/1", timeout=10).status_code == 401


# ------------------------------------------------------------------ GET /subjects/{id}/attendance-summary
def _by_student(body):
    return {i["student_id"]: i for i in body["items"]}


def test_summary_counts(api, v1, lecturer_ctx, seeded):
    body = _get(api, v1, lecturer_ctx.h, f"/subjects/{seeded.s1}/attendance-summary").json()
    assert body["subject_id"] == seeded.s1 and body["total_sessions"] == 3
    rows_ = _by_student(body)
    assert set(rows_) == {seeded.a, seeded.b, seeded.c}                                  # đủ mọi sinh viên đã ghi danh
    a, b, c = rows_[seeded.a], rows_[seeded.b], rows_[seeded.c]
    assert (a["present_count"], a["absent_count"], a["attendance_rate"]) == (3, 0, 1.0)
    assert (b["present_count"], b["absent_count"]) == (2, 1)                             # 2 lần cùng ngày chỉ tính 1 buổi
    assert b["attendance_rate"] == pytest.approx(0.6667, abs=1e-4)
    assert (c["present_count"], c["absent_count"], c["attendance_rate"]) == (0, 3, 0.0)


def test_summary_date_range_and_empty(api, v1, lecturer_ctx, seeded):
    path = f"/subjects/{seeded.s1}/attendance-summary"
    body = _get(api, v1, lecturer_ctx.h, path, date_from=D2, date_to=D3).json()
    assert body["total_sessions"] == 2 and _by_student(body)[seeded.b]["present_count"] == 1
    empty = _get(api, v1, lecturer_ctx.h, path, date_from="2027-01-01").json()
    assert empty["total_sessions"] == 0 and all(i["attendance_rate"] == 0.0 and i["absent_count"] == 0 for i in empty["items"])


def test_summary_errors(api, v1, lecturer_ctx, seeded):
    assert _get(api, v1, lecturer_ctx.h, f"/subjects/{seeded.s2}/attendance-summary").status_code == 403
    assert _get(api, v1, lecturer_ctx.h, "/subjects/NOPE_ZT/attendance-summary").status_code == 404
    assert _get(api, v1, lecturer_ctx.h, f"/subjects/{seeded.s1}/attendance-summary", date_from="abc").status_code == 422
    assert api.get(f"{v1}/subjects/{seeded.s1}/attendance-summary", timeout=10).status_code == 401