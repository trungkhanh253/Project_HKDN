# Android: phần dữ liệu đồng bộ (DB v21)

Giai đoạn 4, phần dữ liệu: migration v21, trigger, outbox. Theo `sqlite_trigger_contract.md` (Android Database <-> Android Sync).

## 1. Đã làm gì

Nâng DB 20 -> 21 : `DATABASE_VERSION = 21`. `onUpgrade` không còn xóa bảng, chỉ thêm cột/bảng/trigger (v20 -> v21). DB dưới v20 giữ hành vi cũ. 
Cột mới ở 6 bảng : `uuid TEXT` (unique), `updated_at INTEGER` (mili giây). Dữ liệu cũ được điền uuid ngay lúc nâng cấp. 
Bảng mới : `sync_outbox` (hàng đợi thay đổi), `sync_state` (cờ chặn trigger), `sync_meta` (`last_seq`, `device_id`). 
Trigger : 3 trigger/bảng (insert, update, delete), tổng 18. Trigger INSERT tự gán `uuid` vì code app hiện tại không truyền uuid. 
Hàm cho người làm Sync : `applyRemote(Runnable)`, `enqueueAllForSync()`, `getLastSeq()`, `setLastSeq(long)`, `resetSyncAfterRestore()`. 
Restore backup : `BackupRestoreHelper.restoreDatabase` gọi `resetSyncAfterRestore()` sau khi restore thành công. 
Test : `androidTest/.../DatabaseV21SyncTest.java` (8 ca). |

6 bảng đồng bộ: `admin`, `subjects`, `students`, `enrollments`, `checkin_history`, `email_recipients`.

## 2. Cách hoạt động ngắn gọn

- Mọi thêm/sửa/xóa trên 6 bảng tự ghi 1 dòng `PENDING` vào `sync_outbox` (không cần sửa code các màn hình).
- Xóa trong app là xóa cứng, nên trigger DELETE ghi lại `uuid` của dòng bị xóa; server nhận `DELETE` thì xóa mềm.
- Khi ghi dữ liệu kéo từ server về, bọc trong `applyRemote(...)`: cờ `is_suppressed = 1` tắt trigger để không đẩy ngược lên server. Cờ được tắt lại trong `finally` và khi mở DB (`onOpen`).
- `payload` trong outbox luôn NULL; Sync Engine đọc dòng hiện tại theo `uuid` khi push.

## 3. Phân chia trách nhiệm với người làm Sync

Chỉ INSERT dòng `PENDING` vào outbox : Đổi `status`, `retry_count`, `last_error`; xóa dòng `SYNCED` 
Giữ `last_seq` trong `sync_meta` (có `getLastSeq/setLastSeq`) : Đọc/ghi `last_seq` quanh mỗi lần pull 
Cung cấp `applyRemote`, `enqueueAllForSync` : Dùng lại hai hàm này, không tự viết lại 

## 4. Lưu ý đã biết

1. **Outbox ghi thêm mỗi lần thay đổi** (không tự gộp). Sync Engine cần gom theo `(table_name, uuid)` khi push và dọn dòng `SYNCED`.
2. **`INSERT OR REPLACE` làm đổi uuid.** `ImportCsvActivity` ghi `enrollments` bằng `INSERT OR REPLACE`: dòng bị thay thế sẽ có uuid mới, và dòng cũ không có "bia mộ". Server cần gộp theo khóa nghiệp vụ `(student_id, subject_id)` (đúng quy tắc chống trùng mã trong kế hoạch).
3. **Tên bảng Android khác server:** Android dùng `students`, `subjects`, `enrollments`, `email_recipients`; `table_name` trong outbox là tên SQLite, Sync Engine tự đổi sang tên server.
4. **Server cần có cột `uuid`** ở mọi bảng thì mới khớp cách đồng bộ này.

## 5. Kiểm thử

Đã chạy các câu SQL trích trực tiếp từ `DatabaseHelper.java` trên DB mẫu có schema v20 thật (kết quả: tất cả đạt):

Nâng cấp v20 có dữ liệu : Số dòng 6 bảng không đổi, mọi dòng có uuid, không trùng, outbox trống 
Thêm dòng : Có uuid, updated_at, 1 dòng outbox `INSERT` (kể cả bảng khóa số tự tăng) 
Sửa dòng : `updated_at` đổi, `uuid` giữ nguyên, ghi `UPDATE` 
Xóa dòng : Ghi `DELETE` 
`is_suppressed = 1` : Thêm/sửa/xóa không sinh outbox, uuid từ server được giữ 
Xóa môn học có người nhận email : Cả hai bảng đều có `DELETE` 
`enqueueAllForSync` : Đưa đủ dòng vào outbox, gọi lần 2 không trùng 
Cài mới : Thêm dữ liệu vẫn ghi outbox 

Chạy lại trên máy thật: Android Studio, chuột phải `DatabaseV21SyncTest` chọn Run (cần thiết bị hoặc giả lập). Ngoài ra nên thử thủ công: cài bản cũ (v20) có dữ liệu, chạy bản mới đè lên, kiểm tra dữ liệu còn nguyên.
