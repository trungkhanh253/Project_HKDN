package com.iritech.irissample.sync.model;

import com.google.gson.annotations.SerializedName;
import java.io.Serializable;
import java.util.Map;

/**
 * Đại diện cho một thay đổi dữ liệu (Change Data Capture)
 * Tương ứng với một dòng trong bảng sync_outbox (local) hoặc bảng seq (server)
 */
public class SyncChange implements Serializable {

    @SerializedName("uuid")
    private String uuid;

    @SerializedName("table_name")
    private String tableName;

    @SerializedName("operation")
    private String operation; // "INSERT", "UPDATE", "DELETE"

    @SerializedName("payload")
    private Map<String, Object> payload; // Dữ liệu các cột của bản ghi

    @SerializedName("updated_at")
    private long updatedAt; // Epoch timestamp (milliseconds)

    @SerializedName("seq")
    private long seq; // Chỉ dùng khi Pull từ Server về (con trỏ sequence)

    public SyncChange() {
    }

    public SyncChange(String uuid, String tableName, String operation, Map<String, Object> payload, long updatedAt) {
        this.uuid = uuid;
        this.tableName = tableName;
        this.operation = operation;
        this.payload = payload;
        this.updatedAt = updatedAt;
    }

    public String getUuid() {
        return uuid;
    }

    public void setUuid(String uuid) {
        this.uuid = uuid;
    }

    public String getTableName() {
        return tableName;
    }

    public void setTableName(String tableName) {
        this.tableName = tableName;
    }

    public String getOperation() {
        return operation;
    }

    public void setOperation(String operation) {
        this.operation = operation;
    }

    public Map<String, Object> getPayload() {
        return payload;
    }

    public void setPayload(Map<String, Object> payload) {
        this.payload = payload;
    }

    public long getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(long updatedAt) {
        this.updatedAt = updatedAt;
    }

    public long getSeq() {
        return seq;
    }

    public void setSeq(long seq) {
        this.seq = seq;
    }

    public boolean isDelete() {
        return "DELETE".equalsIgnoreCase(operation);
    }

    public boolean isInsert() {
        return "INSERT".equalsIgnoreCase(operation);
    }

    public boolean isUpdate() {
        return "UPDATE".equalsIgnoreCase(operation);
    }
}
