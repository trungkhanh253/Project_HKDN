package com.iritech.irissample.sync.data;

import com.iritech.irissample.sync.model.SyncChange;
import java.util.List;

/**
 * Interface trừu tượng cầu nối giữa Sync Engine và Cơ sở dữ liệu SQLite cục bộ
 * Khi Người 1 xong outbox, họ chỉ cần viết SqliteSyncRepository implements interface này.
 */
public interface SyncRepository {

    /**
     * Lấy danh sách các thay đổi đang chờ trong outbox để chuẩn bị push
     * @param limit Số lượng tối đa một lần lấy (ví dụ: 50 hoặc 100)
     */
    List<SyncChange> getPendingChanges(int limit);

    /**
     * Đánh dấu các bản ghi đã được Server nhận thành công (xóa khỏi outbox)
     */
    void markSynced(List<String> uuids);

    /**
     * Đánh dấu các bản ghi bị Server từ chối / lỗi validation
     */
    void markFailed(List<String> uuids, String errorMessage);

    /**
     * Ghi các bản ghi kéo từ Server về vào SQLite cục bộ và cập nhật seq
     * Phải chạy trong 1 Database Transaction để đảm bảo tính nguyên tử.
     * Cần kích hoạt cơ chế chặn trigger (is_suppressed) để tránh vòng lặp sync vô hạn.
     */
    void applyPulledChanges(List<SyncChange> changes, long newSeq);

    /**
     * Đếm số lượng thay đổi còn đang chờ push trong outbox
     */
    int getPendingCount();
}
