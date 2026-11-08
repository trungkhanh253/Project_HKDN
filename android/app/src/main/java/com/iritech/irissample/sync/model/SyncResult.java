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
        SKIPPED_NO_CONFIG,   // Chưa nhập Server URL / Token -> SKIPPED (Worker trả success, không retry)
        SKIPPED_CONCURRENT,  // Đang có tiến trình sync khác đang chạy -> SKIPPED (Worker trả success)
        AUTH_ERROR,          // 401 Unauthorized: Hết hạn token -> FAILURE (Không retry, báo login lại)
        VALIDATION_ERROR,    // 400 Bad Request: Dữ liệu gửi lên sai quy cách -> FAILURE
        NETWORK_ERROR,       // Mất mạng, Timeout, DNS error -> RETRY
        SERVER_ERROR         // 5xx Internal Server Error -> RETRY
    }

    private final SyncStatus status;
    private final int pushedCount;
    private final int pulledCount;
    private final ErrorType errorType;
    private final String message;

    private SyncResult(SyncStatus status, int pushedCount, int pulledCount, ErrorType errorType, String message) {
        this.status = status;
        this.pushedCount = pushedCount;
        this.pulledCount = pulledCount;
        this.errorType = errorType != null ? errorType : ErrorType.NONE;
        this.message = message;
    }

    public static SyncResult success(int pushedCount, int pulledCount) {
        return new SyncResult(SyncStatus.SUCCESS, pushedCount, pulledCount, ErrorType.NONE, "Đồng bộ thành công");
    }

    public static SyncResult error(ErrorType errorType, String message) {
        return new SyncResult(SyncStatus.ERROR, 0, 0, errorType, message);
    }

    public static SyncResult skippedNoConfig() {
        return new SyncResult(SyncStatus.SKIPPED, 0, 0, ErrorType.SKIPPED_NO_CONFIG, "Chưa cấu hình máy chủ hoặc tài khoản");
    }

    public static SyncResult skippedConcurrent() {
        return new SyncResult(SyncStatus.SKIPPED, 0, 0, ErrorType.SKIPPED_CONCURRENT, "Tiến trình đồng bộ đang chạy, bỏ qua");
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
                errorType == ErrorType.SKIPPED_NO_CONFIG ||
                errorType == ErrorType.SKIPPED_CONCURRENT;
    }

    /**
     * Dùng cho WorkManager:
     * Chỉ retry khi là lỗi mạng chập chờn hoặc Server lỗi 5xx.
     * Các lỗi do cấu hình (SKIPPED), 401 (AUTH_ERROR), validation -> Dừng hẳn (failure), tránh hao pin.
     */
    public boolean isRetryable() {
        return errorType == ErrorType.NETWORK_ERROR || errorType == ErrorType.SERVER_ERROR;
    }

    @Override
    public String toString() {
        return "SyncResult{" +
                "status=" + status +
                ", pushedCount=" + pushedCount +
                ", pulledCount=" + pulledCount +
                ", errorType=" + errorType +
                ", message='" + message + '\'' +
                '}';
    }
}
