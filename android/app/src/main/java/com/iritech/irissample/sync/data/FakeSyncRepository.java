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
 * 2. markFailed: chuyển FAILED ngay lập tức khi server từ chối cụ thể.
 * 3. recordBatchFailure: tăng retryCount, nếu >= MAX_RETRIES (5) thì chuyển FAILED.
 * 4. applyPulledChanges: Tự động tắt/bật cờ trigger trong try...finally, cập nhật last_seq,
 *    và TỰ ĐỘNG XÓA/HỦY các dòng PENDING cũ của cùng uuid (Server Wins - chống xung đột ping-pong).
 * 5. Có bảng giả lập sync_meta lưu last_seq.
 * 6. Có hàm enqueueAllForSync() đưa dữ liệu vào outbox.
 */
public class FakeSyncRepository implements SyncRepository {

    public static final int MAX_RETRIES = 5;

    public enum OutboxStatus {
        PENDING,
        SYNCED,
        FAILED,
        CANCELLED // Đã bị Server Wins ghi đè bản mới hơn
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
    private final Map<String, String> syncMeta = new HashMap<>(); // Mô phỏng bảng sync_meta trong SQLite
    private boolean isTriggerSuppressed = false;

    public FakeSyncRepository() {
        syncMeta.put("last_seq", "0");
    }

    @Override
    public synchronized long getLastSeq() {
        String val = syncMeta.get("last_seq");
        try {
            return val != null ? Long.parseLong(val) : 0L;
        } catch (NumberFormatException e) {
            return 0L;
        }
    }

    @Override
    public synchronized void setLastSeq(long seq) {
        syncMeta.put("last_seq", String.valueOf(seq));
    }

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
    public synchronized void applyPulledChanges(List<SyncChange> changes, long newSeq) {
        if (changes == null || changes.isEmpty()) {
            if (newSeq > getLastSeq()) {
                setLastSeq(newSeq);
            }
            return;
        }

        // Bật cờ chặn trigger và đảm bảo luôn reset trong khối finally
        this.isTriggerSuppressed = true;
        try {
            for (SyncChange c : changes) {
                String dbKey = c.getTableName() + "_" + c.getUuid();
                if (c.isDelete()) {
                    appliedDatabase.remove(dbKey);
                } else {
                    appliedDatabase.put(dbKey, c);
                }

                // XÁC NHẬN MỤC 5: Server Wins - Hủy các dòng PENDING cũ của cùng uuid trong outbox
                // Tránh việc lần sau lại push cái cũ đè ngược lại Server
                for (OutboxEntry entry : outboxEntries) {
                    if (entry.status == OutboxStatus.PENDING &&
                            entry.change.getUuid() != null &&
                            entry.change.getUuid().equals(c.getUuid())) {
                        entry.status = OutboxStatus.CANCELLED;
                    }
                }
            }

            // Cập nhật last_seq vào sync_meta trong cùng Transaction
            if (newSeq > getLastSeq()) {
                setLastSeq(newSeq);
            }
        } finally {
            this.isTriggerSuppressed = false; // Luôn hoàn nguyên cờ an toàn
        }
    }

    @Override
    public synchronized void enqueueAllForSync() {
        // Đưa toàn bộ các bản ghi hiện tại trong appliedDatabase vào outbox để push lần đầu
        for (SyncChange c : appliedDatabase.values()) {
            addPendingChange(c);
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
