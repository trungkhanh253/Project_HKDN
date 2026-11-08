package com.iritech.irissample.sync.data;

import com.iritech.irissample.sync.model.SyncChange;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

/**
 * Lớp Fake Repository lưu trữ trên RAM mô phỏng chính xác hành vi của SQLite outbox thật:
 * 1. Chỉ lấy các bản ghi có trạng thái PENDING.
 * 2. markFailed: chuyển trạng thái FAILED ngay lập tức khi server từ chối cụ thể.
 * 3. recordBatchFailure: tăng retryCount, nếu >= MAX_RETRIES (5) thì chuyển FAILED.
 * 4. applyPulledChanges: Tự động tắt/bật cờ trigger trong try...finally.
 * 5. Idempotent Upsert theo table + uuid.
 */
public class FakeSyncRepository implements SyncRepository {

    public static final int MAX_RETRIES = 5;

    public enum OutboxStatus {
        PENDING,
        SYNCED,
        FAILED
    }

    public static class OutboxEntry {
        public final String changeId;
        public final SyncChange change;
        public OutboxStatus status;
        public int retryCount;
        public String lastError;

        public OutboxEntry(String changeId, SyncChange change) {
            this.changeId = changeId;
            this.change = change;
            this.status = OutboxStatus.PENDING;
            this.retryCount = 0;
        }
    }

    private final List<OutboxEntry> outboxEntries = new ArrayList<>();
    private final Map<String, SyncChange> appliedDatabase = new HashMap<>(); // Mô phỏng DB SQLite (Key = Table + UUID)
    private boolean isTriggerSuppressed = false;

    public synchronized void addPendingChange(SyncChange change) {
        if (change != null) {
            String cId = change.getChangeId();
            if (cId == null || cId.isEmpty()) {
                cId = "cid_" + (outboxEntries.size() + 1);
                change.setChangeId(cId);
            }
            outboxEntries.add(new OutboxEntry(cId, change));
        }
    }

    @Override
    public synchronized List<SyncChange> getPendingChanges(int limit) {
        List<SyncChange> pending = new ArrayList<>();
        for (OutboxEntry entry : outboxEntries) {
            if (entry.status == OutboxStatus.PENDING) {
                pending.add(entry.change);
                if (pending.size() >= limit) break;
            }
        }
        return pending;
    }

    @Override
    public synchronized void markSynced(List<String> changeIds) {
        if (changeIds == null || changeIds.isEmpty()) return;
        Iterator<OutboxEntry> iterator = outboxEntries.iterator();
        while (iterator.hasNext()) {
            OutboxEntry entry = iterator.next();
            if (changeIds.contains(entry.changeId)) {
                entry.status = OutboxStatus.SYNCED;
                iterator.remove(); // Xóa khỏi outbox
            }
        }
    }

    @Override
    public synchronized void markFailed(List<String> changeIds, String errorMessage) {
        if (changeIds == null || changeIds.isEmpty()) return;
        for (OutboxEntry entry : outboxEntries) {
            if (changeIds.contains(entry.changeId)) {
                entry.status = OutboxStatus.FAILED;
                entry.lastError = errorMessage;
            }
        }
    }

    @Override
    public synchronized void recordBatchFailure(List<String> changeIds, String errorMessage) {
        if (changeIds == null || changeIds.isEmpty()) return;
        for (OutboxEntry entry : outboxEntries) {
            if (changeIds.contains(entry.changeId)) {
                entry.retryCount++;
                entry.lastError = errorMessage;
                if (entry.retryCount >= MAX_RETRIES) {
                    entry.status = OutboxStatus.FAILED; // Vượt quá 5 lần thì chuyển FAILED
                }
            }
        }
    }

    @Override
    public synchronized void applyPulledChanges(List<SyncChange> changes) {
        if (changes == null || changes.isEmpty()) return;

        // Bật cờ chặn trigger và đảm bảo luôn reset trong khối finally
        this.isTriggerSuppressed = true;
        try {
            // Mô phỏng Idempotent Upsert / Delete trong SQLite (Server Wins)
            for (SyncChange c : changes) {
                String dbKey = c.getTableName() + "_" + c.getUuid();
                if (c.isDelete()) {
                    appliedDatabase.remove(dbKey);
                } else {
                    appliedDatabase.put(dbKey, c);
                }
            }
        } finally {
            this.isTriggerSuppressed = false; // Luôn hoàn nguyên cờ an toàn
        }
    }

    public boolean isTriggerSuppressed() {
        return isTriggerSuppressed;
    }

    @Override
    public synchronized int getPendingCount() {
        int count = 0;
        for (OutboxEntry e : outboxEntries) {
            if (e.status == OutboxStatus.PENDING) count++;
        }
        return count;
    }

    @Override
    public synchronized int getFailedCount() {
        int count = 0;
        for (OutboxEntry e : outboxEntries) {
            if (e.status == OutboxStatus.FAILED) count++;
        }
        return count;
    }

    public synchronized Map<String, SyncChange> getAppliedDatabase() {
        return new HashMap<>(appliedDatabase);
    }

    public synchronized List<OutboxEntry> getAllOutboxEntries() {
        return new ArrayList<>(outboxEntries);
    }
}
