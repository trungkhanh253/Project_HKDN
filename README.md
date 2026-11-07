<<<<<<< HEAD
# Project_HKDN
=======
# Project_HKDN

 Ứng dụng điểm danh bằng dữ liệu khuôn mặt của IriTech **Android Client** (hỗ trợ chế độ độc lập và đồng bộ server) và **Flask Backend** sử dụng cơ sở dữ liệu **PostgreSQL** tích hợp extension **pgvector** nhận diện khuôn mặt.

---

## Công nghệ sử dụng

### 1. Backend & API
* **Framework:** Python Flask (với SQLAlchemy ORM, Flask-Migrate, Alembic)
* **Xử lý bất đồng bộ:** Redis & RQ (Redis Queue) với Worker container riêng biệt
* **Server & Hiệu năng:** Gunicorn kết hợp Gevent (Asynchronous worker)
* **Tài liệu API:** Flasgger (Swagger/OpenAPI UI)
* **Công cụ hỗ trợ:** Pandas, Python-dotenv

### 2. Cơ sở dữ liệu & Hạ tầng
* **Database:** PostgreSQL kèm extension `pgvector` (hỗ trợ lưu trữ và tìm kiếm vector đặc trưng khuôn mặt 192 chiều `VECTOR(192)` từ mô hình MobileFaceNet).
* **Containerization:** Docker & Docker Compose (`postgres`, `redis`, `api`, `worker`).

---

## 📊 Cấu trúc cơ sở dữ liệu (6 Bảng Schema)

Hệ thống quản lý đồng bộ 6 bảng cốt lõi với cơ chế tăng tự động `seq`:
1. **`admin`**: Quản lý tài khoản quản trị hệ thống.
2. **`student`**: Quản lý thông tin sinh viên và trường `face_embedding` (`VECTOR(192)`).
3. **`subject`**: Quản lý danh mục học phần / môn học.
4. **`enrollment`**: Quản lý danh sách sinh viên đăng ký học phần.
5. **`checkin_history`**: Lưu trữ lịch sử điểm danh chi tiết.
6. **`email_recipient`**: Quản lý danh sách nhận thông báo email.

---

## Cơ chế đồng bộ (Sync Mechanism)

* **Sync/Pull:** Đồng bộ dữ liệu từ server về client dựa trên tham số `after_seq` để tối ưu băng thông và cập nhật các thay đổi mới nhất.
* **Sync/Push:** Tiếp nhận và xử lý dữ liệu đẩy lên từ client cho toàn bộ 6 bảng schema một cách nhất quán.

---

## Hướng dẫn cài đặt và Chạy hệ thống qua Docker

### 1. Chuẩn bị môi trường
Đảm bảo bạn đã cài đặt **Docker** và **Docker Compose** trên máy.

### 2. Cấu hình biến môi trường
Tạo file `.env` tại thư mục gốc dựa trên file mẫu `.env.example` và cấu hình các thông số kết nối Database, Redis.

### 3. Build và khởi chạy Docker Containers
Chạy lệnh sau tại thư mục gốc của dự án để build và khởi chạy toàn bộ hệ thống (Postgres, Redis, Flask API, RQ Worker):

```bash
docker compose up --build -d
>>>>>>> fe47247 (<Tuan 1>)
