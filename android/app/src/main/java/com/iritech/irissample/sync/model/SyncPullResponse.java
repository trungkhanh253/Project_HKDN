package com.iritech.irissample.sync.model;

import com.google.gson.annotations.SerializedName;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;

/**
 * Phản hồi từ Server khi kéo dữ liệu mới về (GET /api/v1/sync/pull?since_seq=...&limit=...)
 */
public class SyncPullResponse implements Serializable {

    @SerializedName("new_seq")
    private long newSeq; // Con trỏ sequence mới nhất trên Server

    @SerializedName("has_more")
    private boolean hasMore; // True nếu còn dữ liệu vượt quá limit -> cần lặp lại pull tiếp

    @SerializedName("changes")
    private List<SyncChange> changes; // Danh sách bản ghi mới/sửa/xóa mềm

    public SyncPullResponse() {
        this.changes = new ArrayList<>();
    }

    public SyncPullResponse(long newSeq, boolean hasMore, List<SyncChange> changes) {
        this.newSeq = newSeq;
        this.hasMore = hasMore;
        this.changes = changes != null ? changes : new ArrayList<>();
    }

    public long getNewSeq() {
        return newSeq;
    }

    public void setNewSeq(long newSeq) {
        this.newSeq = newSeq;
    }

    public boolean isHasMore() {
        return hasMore;
    }

    public void setHasMore(boolean hasMore) {
        this.hasMore = hasMore;
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
