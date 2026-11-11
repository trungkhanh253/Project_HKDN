package com.iritech.irissample.sync.data;

import android.content.Context;
import android.content.SharedPreferences;
import android.provider.Settings;

/**
 * Lớp lưu cấu hình thật trên Android sử dụng SharedPreferences
 */
public class AndroidSyncPrefs implements ISyncPrefs {
    private static final String PREF_NAME = "attendance_sync_preferences";
    private static final String KEY_LAST_SEQ = "key_last_seq";
    private static final String KEY_LAST_SYNC_TIME = "key_last_sync_time";
    private static final String KEY_SERVER_URL = "key_server_url";
    private static final String KEY_AUTH_TOKEN = "key_auth_token";
    private static final String KEY_SERVER_MODE = "key_server_mode";

    private static final String KEY_AUTO_SYNC = "key_auto_sync";

    private final SharedPreferences prefs;
    private final String deviceId;

    public AndroidSyncPrefs(Context context) {
        Context appCtx = context.getApplicationContext();
        this.prefs = appCtx.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);

        String id = null;
        try {
            id = Settings.Secure.getString(appCtx.getContentResolver(), Settings.Secure.ANDROID_ID);
        } catch (Exception ignored) {
        }
        this.deviceId = (id != null && !id.isEmpty()) ? id : "android_unknown_device";
    }

    @Override
    public long getLastSeq() {
        return prefs.getLong(KEY_LAST_SEQ, 0L);
    }

    @Override
    public void setLastSeq(long seq) {
        prefs.edit().putLong(KEY_LAST_SEQ, seq).apply();
    }

    @Override
    public long getLastSyncTime() {
        return prefs.getLong(KEY_LAST_SYNC_TIME, 0L);
    }

    @Override
    public void setLastSyncTime(long timestampMs) {
        prefs.edit().putLong(KEY_LAST_SYNC_TIME, timestampMs).apply();
    }

    @Override
    public String getServerUrl() {
        return prefs.getString(KEY_SERVER_URL, "");
    }

    @Override
    public void setServerUrl(String url) {
        prefs.edit().putString(KEY_SERVER_URL, url).apply();
    }

    @Override
    public String getAuthToken() {
        return prefs.getString(KEY_AUTH_TOKEN, "");
    }

    @Override
    public void setAuthToken(String token) {
        prefs.edit().putString(KEY_AUTH_TOKEN, token).apply();
    }

    @Override
    public boolean isServerMode() {
        return prefs.getBoolean(KEY_SERVER_MODE, false);
    }

    @Override
    public void setServerMode(boolean enabled) {
        prefs.edit().putBoolean(KEY_SERVER_MODE, enabled).apply();
    }

    @Override
    public String getDeviceId() {
        return deviceId;
    }


    public boolean isAutoSyncEnabled() {
        return prefs.getBoolean(KEY_AUTO_SYNC, false);
    }

    public void setAutoSyncEnabled(boolean enabled) {
        prefs.edit()
                .putBoolean(KEY_AUTO_SYNC, enabled)
                .apply();
    }


    public String getRefreshToken() {
        return prefs.getString("refresh_token", "");
    }

    public void setRefreshToken(String token) {
        prefs.edit()
                .putString("refresh_token", token)
                .apply();
    }

    public void clearAuthSession() {
        prefs.edit()
                .remove(KEY_AUTH_TOKEN)
                .remove("refresh_token")
                .apply();
    }


}
