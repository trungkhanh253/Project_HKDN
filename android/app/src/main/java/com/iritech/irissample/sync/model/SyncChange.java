package com.iritech.irissample.sync.model;

import com.google.gson.JsonObject;
import com.google.gson.annotations.SerializedName;
import java.io.Serializable;

/**
 * Đại diện cho một thay đổi dữ liệu (Change Data Capture)
 * Tương ứng với một dòng trong bảng sync_outbox (local) hoặc bảng seq (server)
 *
 * Lưu ý: payload sử dụng JsonObject của Gson để tránh lỗi tự ép kiểu số nguyên thành Double (5 -> 5.0)
 * seq dùng kiểu Wrapper Long (nullable) vì khi Push từ local lên seq sẽ là null.
 */
public class SyncChange implements Serializable {

    @SerializedName("uuid")
    private String uuid;

    @SerializedName("table_name")
    private String tableName;

    @SerializedName("operation")
    private String operation; // "INSERT", "UPDATE", "DELETE"

    @SerializedName("payload")
    private JsonObject payload; // Dùng JsonObject để an toàn kiểu dữ liệu (tránh bug 5.0 của Map)

    @SerializedName("updated_at")
    private long updatedAt; // Epoch timestamp (milliseconds)

    @SerializedName("seq")
    private Long seq; // Nullable: Client Push lên thì null, Server trả về thì có giá trị

    public SyncChange() {
    }

    public SyncChange(String uuid, String tableName, String operation, JsonObject payload, long updatedAt) {
        this.uuid = uuid;
        this.tableName = tableName;
        this.operation = operation;
        this.payload = payload;
        this.updatedAt = updatedAt;
        this.seq = null; // Khi tạo ở client, seq mặc định là null
    }

    public SyncChange(String uuid, String tableName, SyncOperation operation, JsonObject payload, long updatedAt) {
        this(uuid, tableName, operation != null ? operation.name() : null, payload, updatedAt);
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
        this.operation = operation != null ? operation.toUpperCase().trim() : null;
    }

    public void setOperation(SyncOperation op) {
        this.operation = op != null ? op.name() : null;
    }

    public JsonObject getPayload() {
        return payload;
    }

    public void setPayload(JsonObject payload) {
        this.payload = payload;
    }

    public long getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(long updatedAt) {
        this.updatedAt = updatedAt;
    }

    public Long getSeq() {
        return seq;
    }

    public void setSeq(Long seq) {
        this.seq = seq;
    }

    public boolean isDelete() {
        return SyncOperation.OP_DELETE.equalsIgnoreCase(operation);
    }

    public boolean isInsert() {
        return SyncOperation.OP_INSERT.equalsIgnoreCase(operation);
    }

    public boolean isUpdate() {
        return SyncOperation.OP_UPDATE.equalsIgnoreCase(operation);
    }

    public boolean isValidOperation() {
        return isInsert() || isUpdate() || isDelete();
    }

    /**
     * Với DELETE, payload có thể null (chỉ cần uuid và table_name để xóa).
     * Với INSERT/UPDATE, bắt buộc payload phải có dữ liệu.
     */
    public boolean isValidChange() {
        if (uuid == null || uuid.trim().isEmpty()) return false;
        if (tableName == null || tableName.trim().isEmpty()) return false;
        if (!isValidOperation()) return false;
        if (!isDelete() && payload == null) return false;
        return true;
    }
}
