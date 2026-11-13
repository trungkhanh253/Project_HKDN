package com.iritech.irissample.sync.data;

/**
 * Interface cấu hình & trạng thái đồng bộ
 * Tách biệt để chạy được cả trên Android (SharedPreferences) và JVM Test (RAM).
 */
public interface ISyncPrefs {
    long getLastSeq();
    void setLastSeq(long seq);

    long getLastSyncTime();
    void setLastSyncTime(long timestampMs);

    String getServerUrl();
    void setServerUrl(String url);

    String getAuthToken();
    void setAuthToken(String token);

    boolean isServerMode();
    void setServerMode(boolean enabled);

    String getDeviceId();
}
