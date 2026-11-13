# Hướng dẫn chạy và kiểm thử Project_HKDN (Server)

Lệnh bên dưới viết cho **Windows PowerShell**, chạy ở thư mục gốc repo (nơi có `docker-compose.yml`), trừ khi có ghi chú khác.

## 1. Yêu cầu
- Docker Desktop (Engine running; trên Windows cần WSL: `wsl --install` rồi khởi động lại máy)
- Git, Python 3.10+ (để chạy pytest từ máy host)

## 2. Cấu hình môi trường
```powershell
copy .env.example .env
```
Mở `.env` và đặt `POSTGRES_PASSWORD`; phần mật khẩu trong `DATABASE_URL` và `TEST_DATABASE_URL` phải **giống hệt**. Không commit `.env`.

> docker-compose.yml có mật khẩu mặc định dự phòng; nếu không tạo `.env`, hệ thống vẫn chạy với mật khẩu mặc định đó, nên hãy luôn tạo `.env`.

## 3. Khởi động hệ thống
```powershell
docker compose up -d --build
docker compose ps
```
Phải thấy 4 container `hkdn_postgres`, `hkdn_redis`, `hkdn_api`, `hkdn_worker` ở trạng thái Up. (Cảnh báo `version is obsolete` bỏ qua được.)

Kiểm tra API:
```powershell
curl.exe http://localhost:5000/health
```

## 4. Migration (tạo bảng) & Tạo tài khoản Admin mẫu
DB chạy thật:
```powershell
docker compose exec api flask --app "app:create_app()" db upgrade
docker compose exec api python seed_admin.py
```
Tài khoản Admin mẫu được tạo sẵn:
- **Super Admin:** `admin@hkdn.edu.vn` / `admin123` (`admin_id`: `SADM_001`)
- **Giảng viên (Admin):** `lecturer@hkdn.edu.vn` / `lecturer123` (`admin_id`: `ADM_001`)

DB test (thay `MATKHAU` bằng mật khẩu trong `.env`):
```powershell
docker compose exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS attendance_test;"
docker compose exec postgres psql -U postgres -c "CREATE DATABASE attendance_test;"
docker compose exec -e DATABASE_URL=postgresql://postgres:MATKHAU@postgres:5432/attendance_test api flask --app "app:create_app()" db upgrade
docker compose exec postgres psql -U postgres -d attendance_test -c "\dt"
```
Kết quả đúng: 6 bảng nghiệp vụ (`admin`, `students`, `subjects`, `enrollments`, `checkin_history`, `email_recipients`) và `alembic_version`.

## 5. Chạy test
Chạy trong thư mục `server` (không chạy ở thư mục gốc repo, vì pytest sẽ quét nhầm cả file `test_check.py` của nhóm).
```powershell
cd server
python -m pip install -r requirements-dev.txt
python -m pytest              # tất cả
python -m pytest -m db        # schema DB (dùng DB test)
python -m pytest -m api       # API, đồng bộ, bảo mật (dùng DB chạy thật qua server)
```
- Test API tự skip nếu server không phản hồi; test DB tự skip nếu thiếu `TEST_DATABASE_URL`.
- Test API/đồng bộ/bảo mật dùng tài khoản seed: chạy `docker compose exec api python seed_admin.py` trước. Mặc định đăng nhập bằng `admin@hkdn.edu.vn` / `admin123`; đổi bằng `TEST_ADMIN_EMAIL`, `TEST_ADMIN_PASSWORD` trong `.env`. `TEST_API_PREFIX` mặc định là `/api/v1`.
- **xfailed**: chỗ đã ghi nhận đang chờ Lead/nhóm Server quyết định, không phải lỗi của người chạy test. Nếu được sửa đúng, pytest báo **XPASS**.
- **failed** trong `test_security.py` và `test_sync_edge_cases.py` là lỗi/lỗ hổng thật của server đang chờ sửa (không phải lỗi môi trường của bạn); xem danh sách trong Pull Request.
- Các test API ghi dữ liệu mẫu (mã bắt đầu bằng `T`, và `TEST0001`, `TEST0002` của test import CSV) vào DB chạy thật; dọn bằng `docker compose down -v` khi cần.

## 6. Dừng / dọn dẹp
```powershell
docker compose down        # dừng, giữ dữ liệu
docker compose down -v     # dừng và XÓA dữ liệu Postgres (volume pgdata)
```
Nếu đổi `POSTGRES_PASSWORD` sau khi Postgres đã khởi tạo, phải dùng `down -v`.

## 7. Xử lý lỗi thường gặp
| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| `ports are not available ... 5432 ... forbidden by its access permissions` | Windows giữ riêng dải cổng chứa 5432 (kiểm tra: `netsh int ipv4 show excludedportrange protocol=tcp`). Tạo `docker-compose.override.yml` (lưu UTF-8, **không commit**: thêm vào `.git/info/exclude`) với nội dung bên dưới, rồi đặt `TEST_DATABASE_URL` dùng cổng 15432 |
| `go-yaml load error ... L1:C1` | File override bị sai mã hóa; tạo lại bằng VS Code, chọn UTF-8 |
| `password authentication failed` | Mật khẩu trong `.env` khác mật khẩu volume đã khởi tạo: `docker compose down -v` rồi `up` lại |
| `Could not locate a Flask application` | Thêm `--app "app:create_app()"` vào lệnh `flask` |
| `ModuleNotFoundError: flask_sqlalchemy` khi chạy pytest | Đang chạy ở thư mục gốc repo; `cd server` rồi chạy lại |
| `404` ở mọi API | Route chưa được viết: `docker compose exec api flask --app "app:create_app()" routes` |
| Job `/jobs/{id}` luôn `queued` | Container `worker` không chạy hoặc `REDIS_URL` sai: `docker compose logs worker` |
| `connection refused` khi chạy pytest | Container chưa Up (`docker compose ps`) hoặc `TEST_*` trỏ sai cổng |

`docker-compose.override.yml` (đổi cổng Postgres ra máy host sang 15432):
```yaml
services:
  postgres:
    ports: !override
      - "15432:5432"
```