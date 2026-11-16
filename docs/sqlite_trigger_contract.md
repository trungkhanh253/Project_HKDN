# QUY ƯỚC OUTBOX VÀ CHẶN TRIGGER CHO ANDROID 1 (SQLITE)

Tài liệu này dùng để thống nhất giữa **Người 1 (Database Android)** và **Người 3 (Sync Engine Android)**.

---

### 1. Bảng `sync_outbox`
Mỗi khi có thao tác INSERT / UPDATE / DELETE trên bất kỳ bảng nào trong 6 bảng (`admin`, `subjects`, `students`, `enrollments`, `checkin_history`, `email_recipients`), trigger sẽ tự động ghi 1 dòng vào bảng này:

```sql
CREATE TABLE sync_outbox (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL, -- 'INSERT', 'UPDATE', 'DELETE'
    payload TEXT,            -- Chuỗi JSON các cột (đối với DELETE có thể NULL)
    updated_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'SYNCED', 'FAILED', 'CANCELLED'
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX idx_outbox_pending ON sync_outbox (status, change_id ASC);
```

> **Cơ chế tự sinh UUID (Người 1 xác nhận):**
> Khi thêm dữ liệu mới, trigger / default column sẽ tự động sinh UUID trước rồi mới ghi vào outbox, đảm bảo UUID không bao giờ bị rỗng.
> Cột `payload` trigger có thể để NULL, khi push phía Java sẽ tự động bóc tách từ bảng gốc sang JSON.

---

### 2. Bảng `sync_meta` (Lưu con trỏ `last_seq` trong SQLite)
Thay vì lưu `last_seq` trong SharedPreferences, lưu trực tiếp trong SQLite để bảo toàn trạng thái khi **Backup & Restore Database file**:

```sql
CREATE TABLE sync_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
INSERT OR IGNORE INTO sync_meta (key, value) VALUES ('last_seq', '0');
```

---

### 3. Cơ chế chặn Trigger (Tránh vòng lặp sync vô hạn)
Tạo bảng cấu hình trạng thái:
```sql
CREATE TABLE sync_state (
    id INTEGER PRIMARY KEY,
    is_suppressed INTEGER NOT NULL DEFAULT 0
);
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

### 4. Quy tắc An toàn khi Khởi động App & Kéo dữ liệu về (applyRemote)
1. **Khi App khởi động (`DatabaseHelper.onOpen` hoặc `Application.onCreate`):**
   Luôn chạy câu lệnh reset để phòng trường hợp app bị crash giữa chừng lúc đang sync:
   ```sql
   UPDATE sync_state SET is_suppressed = 0 WHERE id = 1;
   ```

2. **Bên trong hàm `applyRemote(List<SyncChange> changes, long newSeq)`:**
   Phải mở Transaction và dùng khối `try ... finally`:
   ```java
   db.beginTransaction();
   try {
       // 1. Bật cờ chặn trigger bên TRONG transaction
       db.execSQL("UPDATE sync_state SET is_suppressed = 1 WHERE id = 1;");

       // 2. Ghi theo thứ tự: Bảng cha trước (admin -> subjects -> students)
       //                     rồi mới đến bảng con (enrollments -> checkin_history -> email_recipients)
       for (SyncChange c : changes) {
           applyChangeToDatabase(db, c);

           // 3. XÁC NHẬN MỤC 5 (Server Wins): Hủy các dòng PENDING cũ của cùng uuid trong outbox
           // Tránh việc lần sau lại push cái cũ đè ngược lại Server
           db.execSQL("UPDATE sync_outbox SET status = 'CANCELLED' WHERE uuid = ? AND status = 'PENDING'", new Object[]{c.getUuid()});
       }

       // 4. Cập nhật last_seq vào bảng sync_meta trong cùng Transaction
       db.execSQL("UPDATE sync_meta SET value = ? WHERE key = 'last_seq'", new Object[]{String.valueOf(newSeq)});

       db.setTransactionSuccessful();
   } finally {
       // Luôn hoàn nguyên cờ an toàn
       db.execSQL("UPDATE sync_state SET is_suppressed = 0 WHERE id = 1;");
       db.endTransaction();
   }
   ```

---

### 5. Hàm `enqueueAllForSync()` (Chuyển mode lần đầu)
Duyệt qua 6 bảng hiện tại, nếu bản ghi chưa có trong `sync_outbox` thì insert vào `sync_outbox` với `operation = 'INSERT'`, `status = 'PENDING'`.
