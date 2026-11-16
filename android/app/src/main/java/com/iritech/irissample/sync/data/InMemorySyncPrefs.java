package com.iritech.irissample.sync.data;

/**
 * Lớp lưu cấu hình tạm trên RAM (dành riêng cho Unit Test trên máy tính)
 */
public class InMemorySyncPrefs implements ISyncPrefs {
    private long lastSeq = 0L;
    private long lastSyncTime = 0L;
    private String serverUrl = "http://127.0.0.1:5000";
    private String authToken = "mock_jwt_token_123456";
    private boolean serverMode = true;
    private String deviceId = "test_device_jvm";

    @Override
    public long getLastSeq() {
        return lastSeq;
    }

    @Override
    public void setLastSeq(long seq) {
        this.lastSeq = seq;
    }

    @Override
    public long getLastSyncTime() {
        return lastSyncTime;
    }

    @Override
    public void setLastSyncTime(long timestampMs) {
        this.lastSyncTime = timestampMs;
    }

    @Override
    public String getServerUrl() {
        return serverUrl;
    }

    @Override
    public void setServerUrl(String url) {
        this.serverUrl = url;
    }

    @Override
    public String getAuthToken() {
        return authToken;
    }

    @Override
    public void setAuthToken(String token) {
        this.authToken = token;
    }

    @Override
    public boolean isServerMode() {
        return serverMode;
    }

    @Override
    public void setServerMode(boolean enabled) {
        this.serverMode = enabled;
    }

    @Override
    public String getDeviceId() {
        return deviceId;
    }

    public void setDeviceId(String deviceId) {
        this.deviceId = deviceId;
    }
}
