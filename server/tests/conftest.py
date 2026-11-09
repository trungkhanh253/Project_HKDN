import os
import pytest
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:5000").rstrip("/")
TEST_DB_URL = os.getenv("TEST_DATABASE_URL")
# Kế hoạch ghi API có phiên bản /api/v1 (openapi.yml hiện chưa có tiền tố; xác nhận với Người 2)
API_PREFIX = os.getenv("TEST_API_PREFIX", "/api/v1").rstrip("/")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def v1(base_url):
    """Địa chỉ gốc của API có phiên bản, ví dụ http://localhost:5000/api/v1"""
    return f"{base_url}{API_PREFIX}"


@pytest.fixture(scope="session")
def api(base_url):
    """Session HTTP; bỏ qua toàn bộ test API nếu server chưa chạy."""
    s = requests.Session()
    try:
        s.get(f"{base_url}/health", timeout=3)
    except requests.RequestException:
        pytest.skip(f"Server không phản hồi tại {base_url} (chạy docker compose up trước)")
    return s


@pytest.fixture
def db():
    """Kết nối DB; mọi thay đổi được rollback sau mỗi test."""
    if not TEST_DB_URL:
        pytest.skip("Chưa đặt TEST_DATABASE_URL")
    psycopg2 = pytest.importorskip("psycopg2")
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
