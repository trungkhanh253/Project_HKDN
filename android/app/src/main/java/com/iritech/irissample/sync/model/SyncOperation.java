package com.iritech.irissample.sync.model;

import com.google.gson.annotations.SerializedName;

/**
 * Các loại thao tác thay đổi dữ liệu (Cố định viết hoa đồng bộ với Server)
 */
public enum SyncOperation {
    @SerializedName("INSERT")
    INSERT,

    @SerializedName("UPDATE")
    UPDATE,

    @SerializedName("DELETE")
    DELETE;

    public static final String OP_INSERT = "INSERT";
    public static final String OP_UPDATE = "UPDATE";
    public static final String OP_DELETE = "DELETE";

    public static SyncOperation fromString(String op) {
        if (op == null) return null;
        for (SyncOperation o : values()) {
            if (o.name().equalsIgnoreCase(op.trim())) {
                return o;
            }
        }
        return null;
    }
}
