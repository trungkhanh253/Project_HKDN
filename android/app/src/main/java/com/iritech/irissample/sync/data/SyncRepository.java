package com.iritech.irissample.sync.data;

import com.iritech.irissample.sync.model.SyncChange;
import java.util.List;

/**
 * Interface trừu tượng cầu nối giữa Sync Engine và Cơ sở dữ liệu SQLite cục bộ
 */
public interface SyncRepository {

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
     * TỰ ĐỘNG bọc trong Database Transaction và TỰ ĐỘNG tắt trigger SQLite trong khối try...finally,
     * đảm bảo cờ chặn trigger luôn được hoàn nguyên an toàn kể cả khi có Exception.
     */
    void applyPulledChanges(List<SyncChange> changes);

    /**
     * Đếm số lượng thay đổi còn đang chờ push (status = PENDING)
     */
    int getPendingCount();

    /**
     * Đếm số lượng thay đổi bị lỗi (status = FAILED) để cảnh báo lên giao diện
     */
    int getFailedCount();
}
