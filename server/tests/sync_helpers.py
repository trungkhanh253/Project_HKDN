"""Hàm dùng chung cho test đồng bộ và bảo mật (theo docs/openapi.yml hiện tại).

Hợp đồng đang áp dụng:
- POST /api/v1/sync/push  body {"students":[...], "subjects":[...], ...} -> {status, applied, skipped, latest_seq}
- GET  /api/v1/sync/pull?after_seq=&limit= -> {after_seq, next_seq, latest_seq, limit, has_more, changes:{bảng:[...]}}
- updated_at / deleted_at là chuỗi ISO-8601 (ví dụ 2026-11-09T11:00:00Z)
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

TABLES = ["admin", "subjects", "students", "enrollments", "checkin_history", "email_recipients"]
DEFAULT_EMAIL = "admin@hkdn.edu.vn"     # tài khoản do server/seed_admin.py tạo
DEFAULT_PASSWORD = "admin123"


def iso(delta_seconds=0):
    t = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_sid():
    return "T" + uuid.uuid4().hex[:8].upper()


def new_code(prefix="SUB"):
    return prefix + uuid.uuid4().hex[:6].upper()


def new_uuid():
    return str(uuid.uuid4())


def creds():
    return (os.getenv("TEST_ADMIN_EMAIL", DEFAULT_EMAIL),
            os.getenv("TEST_ADMIN_PASSWORD", DEFAULT_PASSWORD))


def login(api, v1):
    email, pw = creds()
    return api.post(f"{v1}/auth/login", json={"email": email, "password": pw}, timeout=10)


def auth_headers(api, v1):
    """Header JWT nếu đăng nhập được, ngược lại {} (để test chạy được dù API có đòi token hay không)."""
    r = login(api, v1)
    if r.status_code == 200:
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    return {}


def student(student_id, u=None, name="Test", ts=None, deleted_at=None):
    return {"student_id": student_id, "full_name": name, "email": "t@example.com",
            "phone": "0900000001", "uuid": u or new_uuid(),
            "updated_at": ts or iso(), "deleted_at": deleted_at}


def subject(code, u=None, name="Mon Test", ts=None):
    return {"subject_id": code, "subject_name": name, "uuid": u or new_uuid(),
            "updated_at": ts or iso(), "deleted_at": None}


def push(api, v1, hdr, body):
    return api.post(f"{v1}/sync/push", json=body, headers=hdr, timeout=15)


def pull(api, v1, hdr, after_seq, limit=500):
    return api.get(f"{v1}/sync/pull", params={"after_seq": after_seq, "limit": limit},
                   headers=hdr, timeout=15)


def flatten(body):
    """{'changes': {'students': [...], ...}} -> [(tên_bảng, bản_ghi), ...] sắp theo seq."""
    out = [(t, rec) for t, rows in body["changes"].items() for rec in rows]
    return sorted(out, key=lambda x: x[1]["seq"])


def pull_all(api, v1, hdr, after_seq=0, limit=500):
    """Kéo hết các trang; trả về (danh sách (bảng, bản ghi), next_seq cuối)."""
    records, cur = [], after_seq
    for _ in range(1000):
        r = pull(api, v1, hdr, cur, limit)
        assert r.status_code == 200, f"pull lỗi HTTP {r.status_code}: {r.text[:200]}"
        body = r.json()
        records += flatten(body)
        cur = body["next_seq"]
        if not body["has_more"]:
            return records, cur
    raise AssertionError("pull không kết thúc (has_more luôn True)")


def latest_seq(api, v1, hdr):
    r = pull(api, v1, hdr, 0, limit=1)
    assert r.status_code == 200, f"pull lỗi HTTP {r.status_code}"
    return r.json()["latest_seq"]


def rows(records, table, **match):
    return [rec for t, rec in records
            if t == table and all(rec.get(k) == v for k, v in match.items())]
