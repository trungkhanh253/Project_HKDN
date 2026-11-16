package com.iritech.irissample.sync.model;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

/**
 * Tiện ích đọc dữ liệu an toàn từ JsonObject của Gson
 * Chống văng Exception khi:
 * 1. Thiếu key (key không tồn tại trong JSON)
 * 2. Key có giá trị null từ JSON (JsonNull)
 */
public class JsonHelper {

    public static boolean hasValidValue(JsonObject json, String key) {
        if (json == null || key == null || !json.has(key)) {
            return false;
        }
        JsonElement element = json.get(key);
        return element != null && !element.isJsonNull();
    }

    public static String getString(JsonObject json, String key, String defaultValue) {
        if (!hasValidValue(json, key)) return defaultValue;
        try {
            return json.get(key).getAsString();
        } catch (Exception e) {
            return defaultValue;
        }
    }

    public static Long getLong(JsonObject json, String key, Long defaultValue) {
        if (!hasValidValue(json, key)) return defaultValue;
        try {
            return json.get(key).getAsLong();
        } catch (Exception e) {
            return defaultValue;
        }
    }

    public static Integer getInt(JsonObject json, String key, Integer defaultValue) {
        if (!hasValidValue(json, key)) return defaultValue;
        try {
            return json.get(key).getAsInt();
        } catch (Exception e) {
            return defaultValue;
        }
    }

    public static Boolean getBoolean(JsonObject json, String key, Boolean defaultValue) {
        if (!hasValidValue(json, key)) return defaultValue;
        try {
            return json.get(key).getAsBoolean();
        } catch (Exception e) {
            return defaultValue;
        }
    }
}
