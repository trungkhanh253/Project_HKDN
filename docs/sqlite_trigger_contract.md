# QUY ƯỚC OUTBOX VÀ CHẶN TRIGGER CHO ANDROID 1 (SQLITE)

Tài liệu này dùng để thống nhất giữa **Người 1 (Database Android)** và **Người 3 (Sync Engine Android)**.

---

### 1. Bảng `sync_outbox`
Mỗi khi có thao tác INSERT / UPDATE / DELETE trên bất kỳ bảng nào (`admin`, `subjects`, `students`, `enrollments`, `checkin_history`), trigger sẽ tự động ghi 1 dòng vào bảng này:

```sql
CREATE TABLE sync_outbox (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL, -- 'INSERT', 'UPDATE', 'DELETE'
    payload TEXT,            -- Chuỗi JSON các cột (đối với DELETE có thể NULL)
    updated_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'SYNCED', 'FAILED'
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX idx_outbox_pending ON sync_outbox (status, change_id ASC);
```

> **Lưu ý tương thích Android compileSdk 29 (SQLite 3.22/3.28):**
> Hàm `json_object()` có thể không có sẵn trên một số phiên bản Android cũ.
> **Cách an toàn nhất:** Trigger chỉ cần lưu: `uuid`, `table_name`, `operation`, `updated_at` (cột `payload` để NULL).
> Khi code Java (`SyncRepository`) chuẩn bị push, Java sẽ đọc trực tiếp dòng hiện tại từ bảng tương ứng theo `uuid` để tạo JSON payload. Cách này chạy được 100% trên mọi dòng máy Android!

---

### 2. Cơ chế chặn Trigger (Tránh vòng lặp sync vô hạn)
Tạo bảng cấu hình trạng thái:
```sql
CREATE TABLE sync_state (
    id INTEGER PRIMARY KEY,
    is_suppressed INTEGER NOT NULL DEFAULT 0
);
-- Bắt buộc insert dòng khởi tạo ngay trong onCreate / onUpgrade:
INSERT OR IGNORE INTO sync_state (id, is_suppressed) VALUES (1, 0);
```

**Trong tất cả các Trigger SQLite, thêm điều kiện `WHEN`:**
```sql
-- 1. Trigger INSERT
CREATE TRIGGER trg_student_insert AFTER INSERT ON students
WHEN (SELECT is_suppressed FROM sync_state WHERE id = 1) = 0
BEGIN
    INSERT INTO sync_outbox (uuid, table_name, operation, updated_at)
    VALUES (NEW.uuid, 'students', 'INSERT', strftime('%s','now') * 1000);
END;

-- 2. Trigger UPDATE
CREATE TRIGGER trg_student_update AFTER UPDATE ON students
WHEN (SELECT is_suppressed FROM sync_state WHERE id = 1) = 0
BEGIN
    INSERT INTO sync_outbox (uuid, table_name, operation, updated_at)
    VALUES (NEW.uuid, 'students', 'UPDATE', strftime('%s','now') * 1000);
END;

-- 3. Trigger DELETE (Lấy OLD.uuid)
CREATE TRIGGER trg_student_delete AFTER DELETE ON students
WHEN (SELECT is_suppressed FROM sync_state WHERE id = 1) = 0
BEGIN
    INSERT INTO sync_outbox (uuid, table_name, operation, updated_at)
    VALUES (OLD.uuid, 'students', 'DELETE', strftime('%s','now') * 1000);
END;
```

---

### 3. Quy tắc An toàn khi Khởi động App & Kéo dữ liệu về (applyPulledChanges)
1. **Khi App khởi động (`DatabaseHelper.onOpen` hoặc `Application.onCreate`):**
   Luôn chạy câu lệnh reset để phòng trường hợp app bị crash giữa chừng lúc đang sync:
   ```sql
   UPDATE sync_state SET is_suppressed = 0 WHERE id = 1;
   ```

2. **Bên trong hàm `applyPulledChanges(changes)`:**
   Phải mở Transaction và dùng khối `try ... finally`:
   ```java
   db.beginTransaction();
   try {
       // Bật cờ chặn trigger bên TRONG transaction
       db.execSQL("UPDATE sync_state SET is_suppressed = 1 WHERE id = 1;");

       // Áp dụng Upsert / Delete theo uuid (Server Wins)
       for (SyncChange c : changes) {
           applyChangeToDatabase(db, c);
       }

       db.setTransactionSuccessful();
   } finally {
       // Luôn hoàn nguyên cờ an toàn
       db.execSQL("UPDATE sync_state SET is_suppressed = 0 WHERE id = 1;");
       db.endTransaction();
   }
   ```

---

### 4. Chính sách Xung đột (Conflict Resolution)
* **Quy tắc: Server Wins (Máy chủ luôn thắng):**
  Bản ghi kéo từ Server về sẽ ghi đè lên dữ liệu local dựa theo `uuid`.
