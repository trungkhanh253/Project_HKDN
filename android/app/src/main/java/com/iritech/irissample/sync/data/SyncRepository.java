package com.iritech.irissample.sync.data;

import com.iritech.irissample.sync.model.SyncChange;
import java.util.List;

/**
 * Interface trừu tượng cầu nối giữa Sync Engine và Cơ sở dữ liệu SQLite cục bộ
 * Cập nhật theo thống nhất mới nhất với Android 1:
 * - last_seq lưu trong bảng sync_meta của SQLite (đi kèm file backup/restore).
 * - Có hàm enqueueAllForSync() khi chuyển từ Standalone sang Server mode.
 * - applyPulledChanges() thực hiện trong transaction, tự tắt trigger và tự hủy các dòng PENDING bị ghi đè.
 */
public interface SyncRepository {

    /**
     * Lấy con trỏ sequence mới nhất từ bảng sync_meta trong SQLite
     */
    long getLastSeq();

    /**
     * Cập nhật con trỏ sequence vào bảng sync_meta trong SQLite
     */
    void setLastSeq(long seq);

    /**
     * Lấy danh sách các thay đổi đang chờ trong outbox để chuẩn bị push (chỉ lấy status = PENDING)
     * Sắp xếp theo thứ tự phát sinh (ORDER BY change_id ASC)
     * @param limit Số lượng tối đa một lần lấy (ví dụ: 50 hoặc 100)
     */
    List<SyncChange> getPendingChanges(int limit);

    /**
     * Đánh dấu các bản ghi outbox đã được Server nhận thành công (xóa khỏi outbox theo change_id)
     */
    void markSynced(List<String> changeIds);

    /**
     * Đánh dấu các bản ghi bị Server từ chối riêng lẻ (chuyển FAILED)
     */
    void markFailed(List<String> changeIds, String errorMessage);

    /**
     * Ghi nhận lỗi cho CẢ MỘT LÔ (khi server ném lỗi 4xx client validation cho cả request)
     * Tăng retry_count cho từng bản ghi trong lô; nếu retry_count >= MAX_RETRIES thì chuyển FAILED
     * để không làm kẹt cứng các lô tiếp theo phía sau.
     */
    void recordBatchFailure(List<String> changeIds, String errorMessage);

    /**
     * Ghi các bản ghi kéo từ Server về vào SQLite cục bộ (Idempotent Upsert)
     * - TỰ ĐỘNG bọc trong Database Transaction.
     * - TỰ ĐỘNG tắt trigger SQLite trong khối try...finally.
     * - Cập nhật last_seq vào bảng sync_meta trong cùng transaction.
     * - TỰ ĐỘNG hủy các dòng PENDING trong outbox của cùng uuid (Server Wins - chống ghi đè ngược).
     */
    void applyPulledChanges(List<SyncChange> changes, long newSeq);

    /**
     * Đưa toàn bộ dữ liệu hiện tại trong 6 bảng vào sync_outbox để chuẩn bị đồng bộ lên Server lần đầu
     * Dùng khi chuyển từ Standalone Mode sang Server Mode.
     */
    void enqueueAllForSync();

    /**
     * Đếm số lượng thay đổi còn đang chờ push (status = PENDING)
     */
    int getPendingCount();

    /**
     * Đếm số lượng thay đổi bị lỗi (status = FAILED) để cảnh báo lên giao diện
     */
    int getFailedCount();
}
