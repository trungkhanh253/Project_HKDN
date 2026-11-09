package com.iritech.irissample.sync.model;

import com.google.gson.annotations.SerializedName;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;

/**
 * Phản hồi từ Server sau khi nhận Push (POST /api/v1/sync/push)
 * Trả về synced_change_ids để xóa chính xác dòng outbox tương ứng.
 */
public class SyncPushResponse implements Serializable {

    @SerializedName("success")
    private boolean success;

    @SerializedName("synced_change_ids")
    private List<String> syncedChangeIds;

    @SerializedName("failed_change_ids")
    private List<String> failedChangeIds;

    @SerializedName("synced_uuids")
    private List<String> syncedUuids;

    @SerializedName("failed_uuids")
    private List<String> failedUuids;

    @SerializedName("error_message")
    private String errorMessage;

    public SyncPushResponse() {
        this.syncedChangeIds = new ArrayList<>();
        this.failedChangeIds = new ArrayList<>();
        this.syncedUuids = new ArrayList<>();
        this.failedUuids = new ArrayList<>();
    }

    public SyncPushResponse(boolean success, List<String> syncedChangeIds, List<String> failedChangeIds, String errorMessage) {
        this.success = success;
        this.syncedChangeIds = syncedChangeIds != null ? syncedChangeIds : new ArrayList<>();
        this.failedChangeIds = failedChangeIds != null ? failedChangeIds : new ArrayList<>();
        this.syncedUuids = this.syncedChangeIds;
        this.failedUuids = this.failedChangeIds;
        this.errorMessage = errorMessage;
    }

    public boolean isSuccess() {
        return success;
    }

    public void setSuccess(boolean success) {
        this.success = success;
    }

    public List<String> getSyncedChangeIds() {
        if (syncedChangeIds != null && !syncedChangeIds.isEmpty()) {
            return syncedChangeIds;
        }
        return syncedUuids != null ? syncedUuids : new ArrayList<String>();
    }

    public void setSyncedChangeIds(List<String> syncedChangeIds) {
        this.syncedChangeIds = syncedChangeIds;
    }

    public List<String> getFailedChangeIds() {
        if (failedChangeIds != null && !failedChangeIds.isEmpty()) {
            return failedChangeIds;
        }
        return failedUuids != null ? failedUuids : new ArrayList<String>();
    }

    public void setFailedChangeIds(List<String> failedChangeIds) {
        this.failedChangeIds = failedChangeIds;
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
}
