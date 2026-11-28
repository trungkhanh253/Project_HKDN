"""TV7 dòng 27 - Kiểm thử API cho Web: 401 khi thiếu token, phân quyền ADMIN/SUPER_ADMIN, phân trang, CORS.

Đặt vào server/tests/. Dùng fixture `api`, `v1`, `base_url` có sẵn trong conftest.py.

CÁCH DÙNG:
1. Hỏi TV4 (Bảo mật & Auth) / TV1 danh sách endpoint mới dành cho Web, điền vào WEB_ENDPOINTS bên dưới.
   Để trống thì các test theo endpoint tự bỏ qua (skip); test CORS vẫn chạy ngay trên endpoint hiện có.
2. Đặt WEB_ORIGIN đúng địa chỉ trang web của nhóm Web (mặc định http://localhost:3000), ví dụ:
   $env:WEB_ORIGIN="http://localhost:5173"; python -m pytest tests/test_web_api.py -q
"""
import os

import pytest

pytestmark = pytest.mark.api

WEB_ORIGIN = os.getenv("WEB_ORIGIN", "http://localhost:3000")
SUPER_ADMIN = ("admin@hkdn.edu.vn", "admin123")       # role SUPER_ADMIN (do seed_admin.py tạo)
LECTURER = ("lecturer@hkdn.edu.vn", "lecturer123")    # role ADMIN

# Điền danh sách endpoint của Web ở đây. Mỗi mục là một dict, ví dụ:
# {"method": "GET", "path": "/students",
#  "super_admin_only": False,                       # True nếu chỉ SUPER_ADMIN được gọi
#  "paginated": True,                               # True nếu có phân trang
#  "page_params": {"size": "limit", "page": "offset"},   # tên tham số phân trang thật của server
#  "items_key": "items"}                            # khóa chứa danh sách trong JSON (bỏ trống nếu trả thẳng mảng)
WEB_ENDPOINTS = [
    # Ba đường dẫn này đã có trong test_security.py của nhóm (GET, đòi token). Kiểm tra lại bằng:
    #   docker compose exec api flask --app "app:create_app()" routes
    {"method": "GET", "path": "/students", "super_admin_only": False, "paginated": True,
     "page_params": {"size": "limit", "page": "offset"}, "items_key": "items"},
    {"method": "GET", "path": "/subjects", "super_admin_only": False, "paginated": True,
     "page_params": {"size": "limit", "page": "offset"}, "items_key": "items"},
    # Kiểm tra thủ công 15/11: /admins không chỉ dành cho SUPER_ADMIN; ADMIN gọi được nhưng chỉ thấy chính mình
    # (xem test_admins_list_is_scoped_by_role).
    {"method": "GET", "path": "/admins", "super_admin_only": False, "paginated": True,
     "page_params": {"size": "limit", "page": "offset"}, "items_key": "items"},
]

_param = pytest.mark.parametrize("ep", WEB_ENDPOINTS or [None],
                                 ids=[f"{e['method']} {e['path']}" for e in WEB_ENDPOINTS] or ["chua-co-endpoint"])


def _token(api, v1, creds):
    r = api.post(f"{v1}/auth/login", json={"email": creds[0], "password": creds[1]}, timeout=10)
    if r.status_code != 200:
        pytest.skip(f"Chưa đăng nhập được {creds[0]} (chạy seed_admin.py)")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _call(api, v1, ep, headers=None, params=None):
    return api.request(ep["method"], f"{v1}{ep['path']}", headers=headers or {}, params=params, timeout=15)


def _need(ep):
    if ep is None:
        pytest.skip("WEB_ENDPOINTS đang trống: xin TV4/TV1 danh sách endpoint của Web")


def _items(body, key):
    if isinstance(body, list):
        return body
    for k in ([key] if key else []) + ["items", "data", "results"]:
        if k and isinstance(body, dict) and isinstance(body.get(k), list):
            return body[k]
    return None


# ---------- CORS (chạy được ngay) ----------
def test_cors_simple_request_allows_web_origin(api, base_url):
    r = api.get(f"{base_url}/health", headers={"Origin": WEB_ORIGIN}, timeout=10)
    allow = r.headers.get("Access-Control-Allow-Origin")
    assert allow in (WEB_ORIGIN, "*"), \
        f"Thiếu hoặc sai header Access-Control-Allow-Origin (nhận được: {allow!r}); trình duyệt sẽ chặn trang web"


@pytest.mark.parametrize("path", ["/auth/login", "/sync/pull"])
def test_cors_preflight_allows_authorization_header(api, v1, path):
    r = api.options(f"{v1}{path}", headers={
        "Origin": WEB_ORIGIN,
        "Access-Control-Request-Method": "POST" if path == "/auth/login" else "GET",
        "Access-Control-Request-Headers": "authorization,content-type"}, timeout=10)
    assert r.status_code in (200, 204), f"Preflight trả HTTP {r.status_code}"
    allow = r.headers.get("Access-Control-Allow-Origin")
    headers = r.headers.get("Access-Control-Allow-Headers", "").lower()
    assert allow in (WEB_ORIGIN, "*"), f"Thiếu Access-Control-Allow-Origin (nhận được: {allow!r})"
    assert "authorization" in headers or headers.strip() == "*", \
        f"Preflight không cho phép header Authorization (Allow-Headers: {headers!r})"


# ---------- 401 khi thiếu / sai token ----------
@_param
def test_endpoint_without_token_is_401(api, v1, ep):
    _need(ep)
    r = _call(api, v1, ep)
    assert r.status_code == 401, f"HTTP {r.status_code}: endpoint Web không đòi token"


@_param
def test_endpoint_with_invalid_token_is_401(api, v1, ep):
    _need(ep)
    r = _call(api, v1, ep, headers={"Authorization": "Bearer not.a.real.token"})
    assert r.status_code == 401


# ---------- Phân quyền ADMIN / SUPER_ADMIN ----------
@_param
def test_super_admin_only_rejects_normal_admin(api, v1, ep):
    _need(ep)
    if not ep.get("super_admin_only"):
        pytest.skip("Endpoint không giới hạn cho SUPER_ADMIN")
    lecturer = _call(api, v1, ep, headers=_token(api, v1, LECTURER))
    boss = _call(api, v1, ep, headers=_token(api, v1, SUPER_ADMIN))
    assert lecturer.status_code == 403, f"ADMIN gọi endpoint SUPER_ADMIN nhận HTTP {lecturer.status_code} (mong 403)"
    assert boss.status_code not in (401, 403), f"SUPER_ADMIN bị chặn: HTTP {boss.status_code}"


@_param
def test_normal_admin_can_use_regular_endpoint(api, v1, ep):
    _need(ep)
    if ep.get("super_admin_only"):
        pytest.skip("Endpoint chỉ dành cho SUPER_ADMIN")
    r = _call(api, v1, ep, headers=_token(api, v1, LECTURER))
    assert r.status_code not in (401, 403), f"ADMIN bị chặn ở endpoint thường: HTTP {r.status_code}"


# ---------- Phân trang ----------
@_param
def test_pagination_limits_page_size(api, v1, ep):
    _need(ep)
    if not ep.get("paginated"):
        pytest.skip("Endpoint không phân trang")
    size_name = ep["page_params"]["size"]
    r = _call(api, v1, ep, headers=_token(api, v1, SUPER_ADMIN), params={size_name: 2})
    assert r.status_code == 200
    items = _items(r.json(), ep.get("items_key"))
    assert items is not None, "Không tìm thấy danh sách trong JSON; điền items_key trong WEB_ENDPOINTS"
    assert len(items) <= 2, f"Yêu cầu tối đa 2 bản ghi nhưng nhận {len(items)}"


@_param
def test_pagination_rejects_invalid_size(api, v1, ep):
    _need(ep)
    if not ep.get("paginated"):
        pytest.skip("Endpoint không phân trang")
    size_name = ep["page_params"]["size"]
    r = _call(api, v1, ep, headers=_token(api, v1, SUPER_ADMIN), params={size_name: -1})
    assert r.status_code in (400, 422), f"Tham số phân trang sai nhưng nhận HTTP {r.status_code}"


# ---------- Khuôn mặt danh sách và dữ liệu nhạy cảm (theo sheet Checklist nghiệm thu) ----------
SENSITIVE_KEYS = {"password", "reset_token", "checkin_password", "face_embedding"}


def _find_keys(obj, bad):
    """Tìm đệ quy các khóa nhạy cảm trong JSON, trả về danh sách khóa tìm thấy."""
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in bad:
                found.add(k)
            found |= _find_keys(v, bad)
    elif isinstance(obj, list):
        for v in obj:
            found |= _find_keys(v, bad)
    return found


@_param
def test_list_response_has_standard_envelope(api, v1, ep):
    """Sheet: danh sách trả {items, total, limit, offset}."""
    _need(ep)
    if not ep.get("paginated"):
        pytest.skip("Endpoint không phân trang")
    size_name = ep["page_params"]["size"]
    r = _call(api, v1, ep, headers=_token(api, v1, SUPER_ADMIN), params={size_name: 2})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict), "Danh sách phải là object có items/total/limit/offset, không phải mảng trần"
    missing = {"items", "total", "limit", "offset"} - set(body)
    assert not missing, f"Thiếu khóa: {sorted(missing)}"
    assert body["limit"] == 2, f"limit trả về {body['limit']} khác limit đã yêu cầu (2)"
    assert len(body["items"]) <= body["limit"]
    assert body["total"] >= len(body["items"])


@_param
def test_responses_do_not_expose_sensitive_fields(api, v1, ep):
    """Sheet (TV4): không API nào trả password, reset_token, checkin_password, face_embedding."""
    _need(ep)
    if ep["method"].upper() != "GET":
        pytest.skip("Chỉ kiểm tra endpoint đọc dữ liệu (GET)")
    r = _call(api, v1, ep, headers=_token(api, v1, SUPER_ADMIN))
    assert r.status_code == 200, f"HTTP {r.status_code}"
    leaked = _find_keys(r.json(), SENSITIVE_KEYS)
    assert not leaked, f"Phản hồi đang trả trường nhạy cảm: {sorted(leaked)}"


# ---------- Phạm vi dữ liệu theo vai trò (kết quả kiểm tra thủ công 15/11) ----------
def test_admins_list_is_scoped_by_role(api, v1):
    """ADMIN (giảng viên) chỉ thấy chính mình; SUPER_ADMIN thấy tất cả."""
    lec = api.get(f"{v1}/admins", headers=_token(api, v1, LECTURER), timeout=15)
    boss = api.get(f"{v1}/admins", headers=_token(api, v1, SUPER_ADMIN), timeout=15)
    assert lec.status_code == 200 and boss.status_code == 200
    lec_emails = {a["email"] for a in (_items(lec.json(), "items") or [])}
    boss_emails = {a["email"] for a in (_items(boss.json(), "items") or [])}
    assert lec_emails == {LECTURER[0]}, f"ADMIN đang thấy admin khác: {sorted(lec_emails)}"
    assert {SUPER_ADMIN[0], LECTURER[0]} <= boss_emails, "SUPER_ADMIN phải thấy cả hai tài khoản mẫu"
