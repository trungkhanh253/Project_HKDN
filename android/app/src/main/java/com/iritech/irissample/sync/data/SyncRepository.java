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
     * Đánh dấu các bản ghi bị Server từ chối / lỗi validation (chuyển status = FAILED và tăng retry_count)
     * Giúp không bị kẹt hàng đợi vô tận trong getPendingChanges.
     */
    void markFailed(List<String> changeIds, String errorMessage);

    /**
     * Ghi các bản ghi kéo từ Server về vào SQLite cục bộ (Idempotent Upsert)
     * Phải chạy trong một Database Transaction và bật cờ chặn trigger (setTriggerSuppressed(true)).
     */
    void applyPulledChanges(List<SyncChange> changes);

    /**
     * Tạm dừng hoặc kích hoạt lại trigger SQLite (chống vòng lặp sync vô hạn)
     */
    void setTriggerSuppressed(boolean suppressed);

    /**
     * Đếm số lượng thay đổi còn đang chờ push (status = PENDING)
     */
    int getPendingCount();
}
