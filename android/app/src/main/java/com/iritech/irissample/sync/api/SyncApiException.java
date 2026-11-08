package com.iritech.irissample.sync.api;

/**
 * Exception thống nhất cho tất cả các lỗi HTTP (Mock lẫn Retrofit thật)
 * Giúp SyncManager bắt lỗi và phân loại ErrorType giống nhau 100%.
 */
public class SyncApiException extends Exception {
    private final int httpCode;

    public SyncApiException(int httpCode, String message) {
        super(message);
        this.httpCode = httpCode;
    }

    public int getHttpCode() {
        return httpCode;
    }

    public boolean isAuthError() {
        return httpCode == 401 || httpCode == 403;
    }

    public boolean isServerError() {
        return httpCode >= 500 && httpCode < 600;
    }

    public boolean isClientError() {
        return httpCode >= 400 && httpCode < 500;
    }
}
