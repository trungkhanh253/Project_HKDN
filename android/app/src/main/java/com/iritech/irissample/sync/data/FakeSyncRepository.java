package com.iritech.irissample.sync.data;

import com.iritech.irissample.sync.model.SyncChange;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

/**
 * Lớp Fake Repository lưu trữ trên RAM phục vụ Unit Test và chạy thử nghiệm
 */
public class FakeSyncRepository implements SyncRepository {

    private final List<SyncChange> outbox = new ArrayList<>();
    private final List<SyncChange> appliedPulledChanges = new ArrayList<>();
    private final Map<String, String> failedMap = new HashMap<>();
    private long lastAppliedSeq = 0L;

    public void addPendingChange(SyncChange change) {
        if (change != null) {
            outbox.add(change);
        }
    }

    @Override
    public synchronized List<SyncChange> getPendingChanges(int limit) {
        int count = Math.min(limit, outbox.size());
        List<SyncChange> sub = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            sub.add(outbox.get(i));
        }
        return sub;
    }

    @Override
    public synchronized void markSynced(List<String> uuids) {
        if (uuids == null || uuids.isEmpty()) return;
        Iterator<SyncChange> iterator = outbox.iterator();
        while (iterator.hasNext()) {
            SyncChange item = iterator.next();
            if (uuids.contains(item.getUuid())) {
                iterator.remove(); // Xóa khỏi outbox khi đã sync thành công
            }
        }
    }

    @Override
    public synchronized void markFailed(List<String> uuids, String errorMessage) {
        if (uuids == null || uuids.isEmpty()) return;
        for (String id : uuids) {
            failedMap.put(id, errorMessage);
        }
    }

    @Override
    public synchronized void applyPulledChanges(List<SyncChange> changes, long newSeq) {
        if (changes != null) {
            appliedPulledChanges.addAll(changes);
        }
        this.lastAppliedSeq = newSeq;
    }

    @Override
    public synchronized int getPendingCount() {
        return outbox.size();
    }

    public List<SyncChange> getAppliedPulledChanges() {
        return appliedPulledChanges;
    }

    public Map<String, String> getFailedMap() {
        return failedMap;
    }

    public long getLastAppliedSeq() {
        return lastAppliedSeq;
    }
}
