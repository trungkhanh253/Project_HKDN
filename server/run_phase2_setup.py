"""
Script tự động khởi tạo và kiểm증 toàn bộ Giai đoạn 2 (Flask, PostgreSQL, Docker, PGVector):
1. Chạy Alembic Migration (tạo extension vector, global_sync_seq, trigger và 6 bảng) trên DB chính.
2. Khởi tạo tài khoản Super Admin & Admin mẫu.
3. Tạo DB kiểm thử (attendance_test) và chạy Migration trên DB kiểm thử.
4. Chạy kiểm tra hạ tầng Giai đoạn 2 (test_check.py).
"""
import os
import subprocess
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def ensure_test_database():
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_pass = os.getenv("POSTGRES_PASSWORD", "kiet2201")
    pg_host = os.getenv("POSTGRES_HOST", "postgres")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    test_db = "attendance_test"

    conn = psycopg2.connect(
        dbname="postgres",
        user=pg_user,
        password=pg_pass,
        host=pg_host,
        port=pg_port,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db,))
        if not cur.fetchone():
            cur.execute(f"CREATE DATABASE {test_db};")
            print(f"-> Đã tạo cơ sở dữ liệu kiểm thử '{test_db}'.")
        else:
            print(f"-> Cơ sở dữ liệu kiểm thử '{test_db}' đã tồn tại.")
    conn.close()
    return f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{test_db}"


def main():
    print("1. Đang chạy Migration trên Database chính (attendance_server)...")
    subprocess.run(
        ["flask", "--app", "app:create_app()", "db", "upgrade"],
        check=True,
    )

    print("2. Đang khởi tạo dữ liệu Admin mẫu (seed_admin.py)...")
    subprocess.run(["python", "seed_admin.py"], check=True)

    print("3. Đang chuẩn bị Database kiểm thử (attendance_test)...")
    test_db_url = ensure_test_database()
    env = os.environ.copy()
    env["DATABASE_URL"] = test_db_url
    subprocess.run(
        ["flask", "--app", "app:create_app()", "db", "upgrade"],
        env=env,
        check=True,
    )

    print("4. Đang kiểm tra trạng thái PostgreSQL + pgvector...")
    subprocess.run(["python", "test_check.py"], check=True)

    print("5. Đang chạy bộ kiểm thử Pytest (Schema + pgvector + API)...")
    test_env = os.environ.copy()
    test_env["TEST_DATABASE_URL"] = test_db_url
    test_env["TEST_BASE_URL"] = "http://localhost:5000"
    subprocess.run(
        ["pytest", "-v"],
        env=test_env,
        check=True,
    )


if __name__ == "__main__":
    main()

