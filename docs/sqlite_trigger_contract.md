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

---

### 2. Cơ chế chặn Trigger (Tránh vòng lặp sync vô hạn)
Tạo bảng cấu hình trạng thái 1 dòng:
```sql
CREATE TABLE sync_state (
    id INTEGER PRIMARY KEY,
    is_suppressed INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO sync_state (id, is_suppressed) VALUES (1, 0);
```

**Trong tất cả các Trigger SQLite, thêm điều kiện `WHEN`:**
```sql
CREATE TRIGGER trg_student_insert AFTER INSERT ON students
WHEN (SELECT is_suppressed FROM sync_state WHERE id = 1) = 0
BEGIN
    INSERT INTO sync_outbox (uuid, table_name, operation, payload, updated_at)
    VALUES (NEW.uuid, 'students', 'INSERT', json_object('student_id', NEW.student_id, 'full_name', NEW.full_name), strftime('%s','now') * 1000);
END;
```

Khi SyncManager kéo dữ liệu từ server về và gọi `applyPulledChanges()`:
1. `UPDATE sync_state SET is_suppressed = 1 WHERE id = 1;`
2. Thực hiện chèn / sửa / xóa các bảng dữ liệu.
3. Trong khối `finally`: `UPDATE sync_state SET is_suppressed = 0 WHERE id = 1;`
