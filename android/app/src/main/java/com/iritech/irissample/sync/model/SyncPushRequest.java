package com.iritech.irissample.sync.model;

import com.google.gson.annotations.SerializedName;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;

/**
 * Gói tin gửi từ Android App lên Server (POST /api/v1/sync/push)
 */
public class SyncPushRequest implements Serializable {

    @SerializedName("device_id")
    private String deviceId;

    @SerializedName("client_timestamp")
    private long clientTimestamp;

    @SerializedName("changes")
    private List<SyncChange> changes;

    public SyncPushRequest() {
        this.changes = new ArrayList<>();
        this.clientTimestamp = System.currentTimeMillis();
    }

    public SyncPushRequest(String deviceId, List<SyncChange> changes) {
        this.deviceId = deviceId;
        this.changes = changes != null ? changes : new ArrayList<>();
        this.clientTimestamp = System.currentTimeMillis();
    }

    public String getDeviceId() {
        return deviceId;
    }

    public void setDeviceId(String deviceId) {
        this.deviceId = deviceId;
    }

    public long getClientTimestamp() {
        return clientTimestamp;
    }

    public void setClientTimestamp(long clientTimestamp) {
        this.clientTimestamp = clientTimestamp;
    }

    public List<SyncChange> getChanges() {
        return changes;
    }

    public void setChanges(List<SyncChange> changes) {
        this.changes = changes;
    }

    public boolean isEmpty() {
        return changes == null || changes.isEmpty();
    }
}
