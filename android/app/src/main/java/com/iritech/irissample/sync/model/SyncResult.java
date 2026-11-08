package com.iritech.irissample.sync.model;

import java.io.Serializable;

/**
 * Kết quả trả về sau chu trình đồng bộ (Push & Pull)
 * Cung cấp đầy đủ thông tin cho SyncWorker để quyết định Result.retry() hay Result.failure()
 * và cho ViewModel/UI để hiển thị thông báo.
 */
public class SyncResult implements Serializable {

    public enum ErrorType {
        NONE,                // Không có lỗi
        SKIPPED_STANDALONE,  // Đang ở Standalone Mode (Worker trả success, không retry)
        SKIPPED_NO_CONFIG,   // Chưa nhập Server URL / Token (Worker trả success, không retry)
        SKIPPED_CONCURRENT,  // Đang có tiến trình sync khác đang chạy (Worker trả success)
        SKIPPED_ABORTED,     // Tác vụ đồng bộ bị hủy ngang giữa chừng (Worker trả success, không ghi nhận lỗi giả)
        AUTH_ERROR,          // 401/403 Unauthorized: Hết hạn token -> FAILURE (Không retry, báo login lại)
        VALIDATION_ERROR,    // 400/404/422 Bad Request: Dữ liệu gửi lên sai quy cách -> FAILURE
        NETWORK_ERROR,       // Mất mạng, Timeout, DNS error -> RETRY
        SERVER_ERROR,        // 5xx, 408, 429: Lỗi máy chủ -> RETRY
        INTERNAL_ERROR       // Bug mã nguồn, NPE, JsonSyntaxException -> FAILURE (Không retry vô ích)
    }

    private final SyncStatus status;
    private final int pushedCount;
    private final int pulledCount;
    private final int failedCount; // Số bản ghi bị từ chối riêng lẻ
    private final ErrorType errorType;
    private final String message;

    private SyncResult(SyncStatus status, int pushedCount, int pulledCount, int failedCount, ErrorType errorType, String message) {
        this.status = status;
        this.pushedCount = pushedCount;
        this.pulledCount = pulledCount;
        this.failedCount = failedCount;
        this.errorType = errorType != null ? errorType : ErrorType.NONE;
        this.message = message;
    }

    public static SyncResult success(int pushedCount, int pulledCount, int failedCount) {
        String msg = "Đồng bộ thành công (Đẩy: " + pushedCount + ", Kéo: " + pulledCount +
                (failedCount > 0 ? ", Bị từ chối: " + failedCount : "") + ")";
        return new SyncResult(SyncStatus.SUCCESS, pushedCount, pulledCount, failedCount, ErrorType.NONE, msg);
    }

    public static SyncResult error(ErrorType errorType, String message) {
        return new SyncResult(SyncStatus.ERROR, 0, 0, 0, errorType, message);
    }

    public static SyncResult skippedStandalone() {
        return new SyncResult(SyncStatus.SKIPPED, 0, 0, 0, ErrorType.SKIPPED_STANDALONE, "Đang ở chế độ cục bộ (Standalone Mode)");
    }

    public static SyncResult skippedNoConfig() {
        return new SyncResult(SyncStatus.SKIPPED, 0, 0, 0, ErrorType.SKIPPED_NO_CONFIG, "Chưa cấu hình máy chủ hoặc tài khoản");
    }

    public static SyncResult skippedConcurrent() {
        return new SyncResult(SyncStatus.SKIPPED, 0, 0, 0, ErrorType.SKIPPED_CONCURRENT, "Tiến trình đồng bộ đang chạy, bỏ qua");
    }

    public static SyncResult skippedAborted() {
        return new SyncResult(SyncStatus.SKIPPED, 0, 0, 0, ErrorType.SKIPPED_ABORTED, "Tác vụ đồng bộ đã bị hủy ngang (Aborted)");
    }

    public SyncStatus getStatus() {
        return status;
    }

    public int getPushedCount() {
        return pushedCount;
    }

    public int getPulledCount() {
        return pulledCount;
    }

    public int getFailedCount() {
        return failedCount;
    }

    public ErrorType getErrorType() {
        return errorType;
    }

    public String getMessage() {
        return message;
    }

    public boolean isSuccess() {
        return status == SyncStatus.SUCCESS;
    }

    public boolean isSkipped() {
        return status == SyncStatus.SKIPPED ||
                errorType == ErrorType.SKIPPED_STANDALONE ||
                errorType == ErrorType.SKIPPED_NO_CONFIG ||
                errorType == ErrorType.SKIPPED_CONCURRENT ||
                errorType == ErrorType.SKIPPED_ABORTED;
    }

    public boolean isAborted() {
        return errorType == ErrorType.SKIPPED_ABORTED;
    }

    /**
     * Dùng cho WorkManager:
     * Chỉ retry khi là lỗi mạng chập chờn hoặc Server lỗi 5xx/408/429.
     * Các lỗi logic, auth, validation, internal bug -> FAILURE, không retry để tránh hao pin/vòng lặp vô hạn.
     */
    public boolean isRetryable() {
        return errorType == ErrorType.NETWORK_ERROR || errorType == ErrorType.SERVER_ERROR;
    }

    @Override
    public String toString() {
        return "SyncResult{" +
                "status=" + status +
                ", pushed=" + pushedCount +
                ", pulled=" + pulledCount +
                ", failed=" + failedCount +
                ", errorType=" + errorType +
                ", message='" + message + '\'' +
                '}';
    }
}
