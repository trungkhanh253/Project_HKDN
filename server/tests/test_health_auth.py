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


def test_login_with_wrong_credentials_returns_401(api, v1):
    r = api.post(
        f"{v1}/auth/login",
        json={"email": "nonexistent@hkdn.edu.vn", "password": "wrongpassword"},
        timeout=5,
    )
    assert r.status_code == 401
    assert "error" in r.json()


def test_login_and_refresh_flow(api, v1):
    # Đảm bảo tài khoản admin mẫu tồn tại thông qua sync/push trước khi test login
    api.post(
        f"{v1}/sync/push",
        json={
            "admin": [
                {
                    "admin_id": "SADM_001",
                    "uuid": "00000000-0000-4000-8000-000000000001",
                    "email": "admin@hkdn.edu.vn",
                    "password": "admin123",
                    "full_name": "Super Admin",
                    "role": "SUPER_ADMIN",
                }
            ]
        },
        timeout=5,
    )

    r_login = api.post(
        f"{v1}/auth/login",
        json={"email": "admin@hkdn.edu.vn", "password": "admin123"},
        timeout=5,
    )
    assert r_login.status_code == 200
    data = r_login.json()
    assert "access_token" in data
    assert "refresh_token" in data

    r_refresh = api.post(
        f"{v1}/auth/refresh",
        headers={"Authorization": f"Bearer {data['refresh_token']}"},
        timeout=5,
    )
    assert r_refresh.status_code == 200
    assert "access_token" in r_refresh.json()
