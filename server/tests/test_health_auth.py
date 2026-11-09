import pytest

pytestmark = pytest.mark.api


def test_health_ok(api, base_url):
    # Kế hoạch: "kiểm tra kết nối (GET /health)"
    r = api.get(f"{base_url}/health", timeout=5)
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


def test_refresh_without_token_is_rejected(api, v1):
    r = api.post(f"{v1}/auth/refresh", timeout=5)
    # 401 (thiếu token) hoặc 422 (JWT không hợp lệ) đều chấp nhận
    assert r.status_code in (401, 422)


def test_refresh_with_garbage_token_is_rejected(api, v1):
    r = api.post(
        f"{v1}/auth/refresh",
        headers={"Authorization": "Bearer not.a.real.token"},
        timeout=5,
    )
    assert r.status_code in (401, 422)
