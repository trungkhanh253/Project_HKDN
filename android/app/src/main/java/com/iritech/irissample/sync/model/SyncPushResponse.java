package com.iritech.irissample.sync.model;

import com.google.gson.annotations.SerializedName;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;

/**
 * Phản hồi từ Server sau khi nhận Push (POST /api/v1/sync/push)
 * Hỗ trợ Partial Success: Cho biết rõ UUID nào thành công để xóa khỏi outbox,
 * UUID nào thất bại để giữ lại hoặc đánh dấu lỗi.
 */
public class SyncPushResponse implements Serializable {

    @SerializedName("success")
    private boolean success;

    @SerializedName("synced_uuids")
    private List<String> syncedUuids;

    @SerializedName("failed_uuids")
    private List<String> failedUuids;

    @SerializedName("error_message")
    private String errorMessage;

    public SyncPushResponse() {
        this.syncedUuids = new ArrayList<>();
        this.failedUuids = new ArrayList<>();
    }

    public SyncPushResponse(boolean success, List<String> syncedUuids, List<String> failedUuids, String errorMessage) {
        this.success = success;
        this.syncedUuids = syncedUuids != null ? syncedUuids : new ArrayList<>();
        this.failedUuids = failedUuids != null ? failedUuids : new ArrayList<>();
        this.errorMessage = errorMessage;
    }

    public boolean isSuccess() {
        return success;
    }

    public void setSuccess(boolean success) {
        this.success = success;
    }

    public List<String> getSyncedUuids() {
        return syncedUuids;
    }

    public void setSyncedUuids(List<String> syncedUuids) {
        this.syncedUuids = syncedUuids;
    }

    public List<String> getFailedUuids() {
        return failedUuids;
    }

    public void setFailedUuids(List<String> failedUuids) {
        this.failedUuids = failedUuids;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public void setErrorMessage(String errorMessage) {
        this.errorMessage = errorMessage;
    }

    public boolean hasFailures() {
        return failedUuids != null && !failedUuids.isEmpty();
    }
}
