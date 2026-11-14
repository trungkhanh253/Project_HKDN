"""Test bảo mật cơ bản cho xác thực và đồng bộ.

Test thường (không xfail) mà ĐỎ nghĩa là có lỗ hổng cần sửa.
Test xfail là điểm cần Lead xác nhận có phải thiết kế cố ý hay không.
"""
import base64
import hashlib
import hmac
import json
import time

import pytest

from sync_helpers import (auth_headers, creds, iso, latest_seq, login, new_uuid,
                          pull_all, push, rows)

pytestmark = pytest.mark.api

# Khóa dự phòng cứng trong server/app/auth.py (_get_secret) khi SECRET_KEY không được cấu hình.
DEFAULT_SECRET = "hkdn-default-secret-key-2026"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _forge_token(admin: dict, secret: str, token_type: str = "refresh") -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": admin["admin_id"], "email": admin["email"],
                               "role": admin.get("role", "ADMIN"), "type": token_type,
                               "iat": now, "exp": now + 600}, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(sig)}"


@pytest.fixture(scope="module")
def session(api, v1):
    r = login(api, v1)
    if r.status_code != 200:
        pytest.skip("Chưa đăng nhập được: chạy `docker compose exec api python seed_admin.py` "
                    "hoặc đặt TEST_ADMIN_EMAIL / TEST_ADMIN_PASSWORD")
    return r.json()


# ---------- yêu cầu token ----------

@pytest.mark.parametrize("method,path", [
    ("post", "/sync/push"),
    ("get", "/sync/pull"),
    ("get", "/sync/status"),
    ("post", "/import/csv"),
    ("get", "/students"),
    ("get", "/subjects"),
    ("get", "/admins"),
    ("get", "/jobs/khong-ton-tai"),
])
def test_data_endpoints_require_token(api, v1, method, path):
    kwargs = {"json": {}} if path == "/sync/push" else {}

    r = getattr(api, method)(
        f"{v1}{path}",
        timeout=10,
        **kwargs
    )

    assert r.status_code == 401, (
        f"HTTP {r.status_code}: "
        f"{method.upper()} {path} không yêu cầu JWT"
    )

# def test_data_endpoints_require_token(api, v1, method, path):
#     """routes.py hiện không kiểm tra token ở các endpoint này. Bảng admin nằm trong đồng bộ,
#     và import CSV (type=admin) nhận cả cột role, nên không cần đăng nhập vẫn tạo được SUPER_ADMIN."""
#     kwargs = {"json": {}} if path == "/sync/push" else {}
#     r = getattr(api, method)(f"{v1}{path}", timeout=10, **kwargs)
#     assert r.status_code in (401, 403), f"HTTP {r.status_code}: endpoint đồng bộ không đòi token"


# ---------- JWT ----------
def test_forged_token_signed_with_default_secret_is_rejected(api, v1, session):
    """docker-compose.yml không truyền SECRET_KEY vào container api nên server rơi về khóa mặc định
    nằm công khai trong mã nguồn; ai cũng ký được token hợp lệ."""
    real = api.post(f"{v1}/auth/refresh",
                    headers={"Authorization": f"Bearer {session['refresh_token']}"}, timeout=10)
    assert real.status_code == 200, "điều kiện tiên quyết: refresh token thật phải dùng được"
    forged = _forge_token(session["admin"], DEFAULT_SECRET)
    r = api.post(f"{v1}/auth/refresh", headers={"Authorization": f"Bearer {forged}"}, timeout=10)
    assert r.status_code == 401, "server chấp nhận token ký bằng khóa mặc định trong mã nguồn"


def test_access_token_cannot_be_used_to_refresh(api, v1, session):
    r = api.post(f"{v1}/auth/refresh",
                 headers={"Authorization": f"Bearer {session['access_token']}"}, timeout=10)
    assert r.status_code == 401


@pytest.mark.xfail(strict=False, reason=(
    "verify_password chấp nhận chính chuỗi băm SHA-256 làm mật khẩu (pass-the-hash), "
    "và SHA-256 không muối. Có thể là cố ý để tương thích Android; Lead xác nhận."))
def test_login_rejects_stored_hash_as_password(api, v1, session):
    _, pw = creds()
    email, _ = creds()
    r = api.post(f"{v1}/auth/login",
                 json={"email": email, "password": hashlib.sha256(pw.encode()).hexdigest()},
                 timeout=10)
    assert r.status_code == 401


# ---------- dữ liệu nhạy cảm khi pull ----------
@pytest.mark.xfail(strict=False, reason=(
    "Admin.to_dict() trả reset_token cho mọi client pull; ai pull được có thể đặt lại mật khẩu "
    "admin khác. Cần Lead xác nhận có thật sự phải đồng bộ reset_token."))
def test_pull_does_not_expose_reset_token(api, v1, session):
    hdr = auth_headers(api, v1)
    cursor = latest_seq(api, v1, hdr)
    aid = "ADM_T" + new_uuid()[:6].upper()
    secret = "RESET" + new_uuid()[:8]
    base = {"admin_id": aid, "email": f"{aid.lower()}@example.com", "full_name": "Test Admin",
            "uuid": new_uuid()}
    try:
        r = push(api, v1, hdr, {"admin": [{**base, "password": "x12345", "reset_token": secret,
                                           "updated_at": iso(0)}]})
        assert r.status_code == 200
        recs, _ = pull_all(api, v1, hdr, cursor)
        found = rows(recs, "admin", admin_id=aid)
        assert found, "không kéo được tài khoản vừa tạo"
        assert all(rec.get("reset_token") != secret for rec in found)
    finally:  # dọn: xóa mềm tài khoản thử
        push(api, v1, hdr, {"admin": [{**base, "updated_at": iso(30), "deleted_at": iso(30)}]})


def test_refresh_token_cannot_access_data(api, v1, session):
    headers = {
        "Authorization": f"Bearer {session['refresh_token']}"
    }

    r = api.get(
        f"{v1}/students",
        headers=headers,
        timeout=10
    )

    assert r.status_code == 401

# ---------- Task 15: Bảo mật API Web ----------

def test_web_students_do_not_expose_sensitive_fields(api, v1, session):
    """GET /students không được trả mật khẩu điểm danh và dữ liệu khuôn mặt."""
    headers = {
        "Authorization": f"Bearer {session['access_token']}"
    }

    r = api.get(
        f"{v1}/students",
        headers=headers,
        timeout=10
    )

    assert r.status_code == 200, r.text

    data = r.json()
    assert "students" in data

    for student in data["students"]:
        assert "checkin_password" not in student
        assert "face_embedding" not in student


def test_web_admins_do_not_expose_sensitive_fields(api, v1, session):
    """GET /admins không được trả thông tin xác thực nhạy cảm."""
    headers = {
        "Authorization": f"Bearer {session['access_token']}"
    }

    r = api.get(
        f"{v1}/admins",
        headers=headers,
        timeout=10
    )

    assert r.status_code == 200, r.text

    data = r.json()
    assert "admins" in data

    sensitive_fields = {
        "password",
        "reset_token",
        "expire_at",
        "face_embedding",
    }

    for admin in data["admins"]:
        assert sensitive_fields.isdisjoint(admin.keys())


def test_cors_allows_configured_origin(api, v1):
    """Frontend được cấu hình phải vượt qua CORS preflight."""
    r = api.options(
        f"{v1}/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
        timeout=10,
    )

    assert r.status_code == 200
    assert (
        r.headers.get("Access-Control-Allow-Origin")
        == "http://localhost:5173"
    )

    allowed_headers = r.headers.get(
        "Access-Control-Allow-Headers", ""
    ).lower()

    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers


def test_cors_rejects_unknown_origin(api, v1):
    """Origin không nằm trong danh sách cho phép không được cấp quyền CORS."""
    r = api.options(
        f"{v1}/auth/login",
        headers={
            "Origin": "http://untrusted.example:5173",
            "Access-Control-Request-Method": "POST",
        },
        timeout=10,
    )

    assert "Access-Control-Allow-Origin" not in r.headers