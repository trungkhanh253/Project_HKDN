package com.iritech.irissample.sync.model;

import com.google.gson.JsonObject;
import com.google.gson.annotations.SerializedName;
import java.io.Serializable;

/**
 * Đại diện cho một thay đổi dữ liệu (Change Data Capture)
 * Tương ứng với một dòng trong bảng sync_outbox (local) hoặc bảng seq (server)
 *
 * - change_id: Định danh duy nhất cho TỪNG DÒNG OUTBOX (để xóa chính xác dòng đó khi push thành công,
 *              tránh xóa nhầm dòng mới phát sinh cùng uuid).
 * - uuid: Khóa định danh nghiệp vụ toàn cục của thực thể (Student, Subject, Checkin, ...).
 * - payload: JsonObject của Gson (tránh lỗi 5 -> 5.0).
 * - seq: Nullable Long (client push lên là null, server trả về có giá trị).
 */
public class SyncChange implements Serializable {

    @SerializedName("change_id")
    private String changeId; // Khóa của dòng thay đổi (outbox ID)

    @SerializedName("uuid")
    private String uuid; // Khóa định danh của bản ghi nghiệp vụ

    @SerializedName("table_name")
    private String tableName;

    @SerializedName("operation")
    private String operation; // "INSERT", "UPDATE", "DELETE"

    @SerializedName("payload")
    private JsonObject payload;

    @SerializedName("updated_at")
    private long updatedAt;

    @SerializedName("seq")
    private Long seq;

    public SyncChange() {
    }

    public SyncChange(String changeId, String uuid, String tableName, String operation, JsonObject payload, long updatedAt) {
        this.changeId = changeId;
        this.uuid = uuid;
        this.tableName = tableName;
        this.operation = operation;
        this.payload = payload;
        this.updatedAt = updatedAt;
        this.seq = null;
    }

    public SyncChange(String changeId, String uuid, String tableName, SyncOperation operation, JsonObject payload, long updatedAt) {
        this(changeId, uuid, tableName, operation != null ? operation.name() : null, payload, updatedAt);
    }

    public String getChangeId() {
        return changeId;
    }

    public void setChangeId(String changeId) {
        this.changeId = changeId;
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

    public boolean isValidChange() {
        if (uuid == null || uuid.trim().isEmpty()) return false;
        if (tableName == null || tableName.trim().isEmpty()) return false;
        if (!isValidOperation()) return false;
        if (!isDelete() && payload == null) return false;
        return true;
    }
}
