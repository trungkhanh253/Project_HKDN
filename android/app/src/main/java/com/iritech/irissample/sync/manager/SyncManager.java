package com.iritech.irissample.sync.manager;

import com.iritech.irissample.sync.api.SyncApi;
import com.iritech.irissample.sync.api.SyncApiException;
import com.iritech.irissample.sync.data.ISyncPrefs;
import com.iritech.irissample.sync.data.SyncRepository;
import com.iritech.irissample.sync.model.SyncChange;
import com.iritech.irissample.sync.model.SyncPullResponse;
import com.iritech.irissample.sync.model.SyncPushRequest;
import com.iritech.irissample.sync.model.SyncPushResponse;
import com.iritech.irissample.sync.model.SyncResult;
import com.iritech.irissample.sync.model.SyncStatus;
import com.iritech.irissample.sync.util.SyncLogger;
import com.iritech.irissample.sync.util.TableMapper;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * BỘ NÃO ĐIỀU PHỐI ĐỒNG BỘ (SYNC MANAGER) - BẢN SẢN XUẤT CHUẨN MỰC
 */
public class SyncManager {

    private static final String TAG = "SyncManager";
    public static final int BATCH_SIZE = 100;
    public static final int MAX_PUSH_BATCHES = 20; // Tối đa 20 lô (2000 bản ghi) mỗi lần sync
    public static final int MAX_PULL_PAGES = 50;    // Tối đa 50 trang mỗi lần sync

    public interface SyncListener {
        void onStatusChanged(SyncStatus status);
        void onSyncFinished(SyncResult result);
    }

    private static SyncManager instance;

    private final SyncApi api;
    private final SyncRepository repository;
    private final ISyncPrefs prefs;
    private final SyncLogger logger;

    private final AtomicBoolean isSyncing = new AtomicBoolean(false);
    private final AtomicBoolean isAborted = new AtomicBoolean(false);
    private final List<SyncListener> listeners = new CopyOnWriteArrayList<>();

    private volatile SyncStatus currentStatus = SyncStatus.IDLE;
    private volatile SyncResult lastResult = null;

    public SyncManager(SyncApi api, SyncRepository repository, ISyncPrefs prefs, SyncLogger logger) {
        this.api = api;
        this.repository = repository;
        this.prefs = prefs;
        this.logger = logger != null ? logger : new SyncLogger.ConsoleLogger();
    }

    public static synchronized void initialize(SyncManager syncManager) {
        instance = syncManager;
    }

    public static synchronized SyncManager getInstance() {
        if (instance == null) {
            throw new IllegalStateException("SyncManager chưa được khởi tạo. Hãy gọi SyncManager.initialize(...) trước.");
        }
        return instance;
    }

    public static synchronized SyncManager getInstanceOrNull() {
        return instance;
    }

    public static synchronized void resetInstanceForTesting() {
        instance = null;
    }

    public void abortCurrentSync() {
        this.isAborted.set(true);
        logger.w(TAG, "Lệnh hủy đồng bộ khẩn cấp (abortCurrentSync) đã được kích hoạt.");
    }

    public boolean isSyncingNow() {
        return isSyncing.get();
    }

    public boolean isSyncing() {
        return isSyncing.get();
    }

    public boolean isAborted() {
        return isAborted.get();
    }

    public void addListener(SyncListener listener) {
        if (listener != null && !listeners.contains(listener)) {
            listeners.add(listener);
            listener.onStatusChanged(currentStatus);
            if (lastResult != null) {
                listener.onSyncFinished(lastResult);
            }
        }
    }

    public void removeListener(SyncListener listener) {
        if (listener != null) {
            listeners.remove(listener);
        }
    }

    private void notifyStatus(SyncStatus status) {
        this.currentStatus = status;
        for (SyncListener l : listeners) {
            try {
                l.onStatusChanged(status);
            } catch (Exception e) {
                logger.e(TAG, "Lỗi khi thông báo trạng thái: " + e.getMessage(), e);
            }
        }
    }

    private void notifyFinished(SyncResult result) {
        this.lastResult = result;
        for (SyncListener l : listeners) {
            try {
                l.onSyncFinished(result);
            } catch (Exception e) {
                logger.e(TAG, "Lỗi khi thông báo kết quả: " + e.getMessage(), e);
            }
        }
    }

    public SyncStatus getCurrentStatus() {
        return currentStatus;
    }

    public SyncResult getLastResult() {
        return lastResult;
    }

    /**
     * THỰC HIỆN CHU TRÌNH ĐỒNG BỘ 2 CHIỀU (BLOCKING METHOD)
     */
    public SyncResult sync() {
        // 1. Chống chạy trùng lặp luồng (Concurrency Guard)
        if (!isSyncing.compareAndSet(false, true)) {
            logger.w(TAG, "Tiến trình đồng bộ đang chạy, bỏ qua lượt gọi trùng.");
            SyncResult skipped = SyncResult.skippedConcurrent();
            notifyStatus(SyncStatus.SKIPPED);
            notifyFinished(skipped);
            return skipped;
        }

        List<String> lastAttemptedBatchIds = new ArrayList<>();

        try {
            // Kiểm tra nếu có lệnh hủy đã được gọi ngay trước khi chu trình kịp bắt đầu
            if (isAborted.get()) {
                logger.w(TAG, "Lệnh hủy đã được kích hoạt trước khi chu trình kịp bắt đầu. Dừng ngay.");
                SyncResult abortResult = SyncResult.skippedAborted();
                notifyStatus(SyncStatus.SKIPPED);
                notifyFinished(abortResult);
                return abortResult;
            }

            // 2. Kiểm tra điều kiện cấu hình
            if (!prefs.isServerMode()) {
                logger.d(TAG, "Đang ở Standalone Mode. Bỏ qua sync.");
                SyncResult result = SyncResult.skippedStandalone();
                notifyStatus(SyncStatus.SKIPPED);
                notifyFinished(result);
                return result;
            }

            if (prefs.getServerUrl() == null || prefs.getServerUrl().trim().isEmpty() ||
                prefs.getAuthToken() == null || prefs.getAuthToken().trim().isEmpty()) {
                logger.w(TAG, "Chưa cấu hình Server URL hoặc Token.");
                SyncResult result = SyncResult.skippedNoConfig();
                notifyStatus(SyncStatus.SKIPPED);
                notifyFinished(result);
                return result;
            }

            currentStatus = SyncStatus.SYNCING;
            notifyStatus(SyncStatus.SYNCING);
            logger.d(TAG, "Bắt đầu chu trình đồng bộ: PUSH -> PULL...");

            int totalPushed = 0;
            int totalPulled = 0;
            int totalFailed = 0;

            // -------------------------------------------------------------------------
            // BƯỚC 1: PUSH NHIỀU LÔ (Xử lý sạch outbox, tối đa MAX_PUSH_BATCHES lô)
            // -------------------------------------------------------------------------
            int pushBatchCount = 0;
            boolean hasMorePending = true;

            while (hasMorePending && pushBatchCount < MAX_PUSH_BATCHES) {
                // Kiểm tra lệnh hủy hoặc ngắt luồng từ Worker
                if (isAborted.get() || Thread.currentThread().isInterrupted()) {
                    logger.w(TAG, "Chu trình push bị hủy ngang (Worker stopped/aborted).");
                    SyncResult abortResult = SyncResult.skippedAborted();
                    notifyStatus(SyncStatus.SKIPPED);
                    notifyFinished(abortResult);
                    return abortResult;
                }

                List<SyncChange> pendingChanges = repository.getPendingChanges(BATCH_SIZE);
                if (pendingChanges == null || pendingChanges.isEmpty()) {
                    hasMorePending = false;
                    break;
                }

                pushBatchCount++;
                lastAttemptedBatchIds.clear();
                for (SyncChange c : pendingChanges) {
                    if (c.getChangeId() != null) {
                        lastAttemptedBatchIds.add(c.getChangeId());
                    }
                    c.setTableName(TableMapper.toServerTableName(c.getTableName()));
                }

                logger.d(TAG, "Đang push lô " + pushBatchCount + " (" + pendingChanges.size() + " bản ghi)...");

                SyncPushRequest pushRequest = new SyncPushRequest(prefs.getDeviceId(), pendingChanges);
                SyncPushResponse pushResponse = api.push(pushRequest);

                if (pushResponse == null) {
                    throw new SyncApiException(500, "Server trả về Push response rỗng");
                }

                List<String> syncedIds = pushResponse.getSyncedChangeIds();
                List<String> failedIds = pushResponse.getFailedChangeIds();

                int handled = (syncedIds == null ? 0 : syncedIds.size()) + (failedIds == null ? 0 : failedIds.size());
                if (handled == 0) {
                    logger.w(TAG, "Lô " + pushBatchCount + ": Server không xác nhận bản ghi nào trong synced hay failed. Dừng push để bảo vệ.");
                    break;
                }

                if (syncedIds != null && !syncedIds.isEmpty()) {
                    repository.markSynced(syncedIds);
                    totalPushed += syncedIds.size();
                    logger.d(TAG, "Lô " + pushBatchCount + ": Push thành công " + syncedIds.size() + " bản ghi.");
                }

                if (failedIds != null && !failedIds.isEmpty()) {
                    String errMsg = pushResponse.getErrorMessage() != null ? pushResponse.getErrorMessage() : "Server rejected item";
                    repository.markFailed(failedIds, errMsg);
                    totalFailed += failedIds.size();
                    logger.w(TAG, "Lô " + pushBatchCount + ": Có " + failedIds.size() + " bản ghi bị từ chối: " + errMsg);
                }

                if (pendingChanges.size() < BATCH_SIZE) {
                    hasMorePending = false;
                }
            }

            if (pushBatchCount >= MAX_PUSH_BATCHES && repository.getPendingCount() > 0) {
                logger.w(TAG, "Đã chạm giới hạn tối đa " + MAX_PUSH_BATCHES + " lô push, vẫn còn " + repository.getPendingCount() + " bản ghi trong outbox.");
            }

            // -------------------------------------------------------------------------
            // BƯỚC 2: PULL VỚI PHÂN TRANG (Kéo dữ liệu mới từ Server về SQLite)
            // -------------------------------------------------------------------------
            boolean hasMore = true;
            long currentSeq = Math.max(repository.getLastSeq(), prefs.getLastSeq());
            int pullPageCount = 0;

            while (hasMore && pullPageCount < MAX_PULL_PAGES) {
                if (isAborted.get() || Thread.currentThread().isInterrupted()) {
                    logger.w(TAG, "Chu trình pull bị hủy ngang (Worker stopped/aborted).");
                    SyncResult abortResult = SyncResult.skippedAborted();
                    notifyStatus(SyncStatus.SKIPPED);
                    notifyFinished(abortResult);
                    return abortResult;
                }

                pullPageCount++;
                logger.d(TAG, "Đang kéo trang " + pullPageCount + " từ server (since_seq = " + currentSeq + ", limit = " + BATCH_SIZE + ")...");
                SyncPullResponse pullResponse = api.pull(currentSeq, BATCH_SIZE);

                if (pullResponse == null) {
                    throw new SyncApiException(500, "Server trả về Pull response rỗng");
                }

                List<SyncChange> changes = pullResponse.getChanges();
                long newSeq = pullResponse.getNewSeq();

                if (pullResponse.isHasMore() && newSeq <= currentSeq) {
                    throw new IllegalStateException("Server báo has_more=true nhưng new_seq không tăng (" + newSeq + " <= " + currentSeq + ")");
                }

                if (changes != null) {
                    for (SyncChange c : changes) {
                        c.setTableName(TableMapper.toLocalTableName(c.getTableName()));
                    }
                }

                repository.applyPulledChanges(changes, newSeq);
                if (changes != null) {
                    totalPulled += changes.size();
                    logger.d(TAG, "Trang " + pullPageCount + ": Đã cập nhật " + changes.size() + " bản ghi vào SQLite local.");
                }

                currentSeq = Math.max(newSeq, currentSeq);
                prefs.setLastSeq(currentSeq);

                hasMore = pullResponse.isHasMore();
            }

            if (pullPageCount >= MAX_PULL_PAGES && hasMore) {
                logger.w(TAG, "Đã chạm giới hạn tối đa " + MAX_PULL_PAGES + " trang pull trong một lần sync.");
            }

            // -------------------------------------------------------------------------
            // BƯỚC 3: HOÀN TẤT THÀNH CÔNG
            // -------------------------------------------------------------------------
            prefs.setLastSyncTime(System.currentTimeMillis());
            SyncResult successResult = SyncResult.success(totalPushed, totalPulled, totalFailed);

            logger.d(TAG, "Đồng bộ hoàn tất thành công! Pushed: " + totalPushed + ", Pulled: " + totalPulled + ", Failed: " + totalFailed);
            notifyStatus(SyncStatus.SUCCESS);
            notifyFinished(successResult);
            return successResult;

        } catch (SyncApiException e) {
            logger.e(TAG, "Lỗi SyncApiException (HTTP " + e.getHttpCode() + "): " + e.getMessage(), e);

            if (!lastAttemptedBatchIds.isEmpty() && (e.isClientValidationError() || e.getHttpCode() == 422)) {
                logger.w(TAG, "Lỗi 4xx cả lô request, tăng retry_count cho " + lastAttemptedBatchIds.size() + " bản ghi trong lô.");
                repository.recordBatchFailure(lastAttemptedBatchIds, "HTTP " + e.getHttpCode() + ": " + e.getMessage());
            }

            SyncResult.ErrorType errorType;
            if (e.isAuthError()) {
                errorType = SyncResult.ErrorType.AUTH_ERROR;
            } else if (e.isRetryableHttp()) {
                errorType = SyncResult.ErrorType.SERVER_ERROR;
            } else {
                errorType = SyncResult.ErrorType.VALIDATION_ERROR;
            }

            SyncResult errResult = SyncResult.error(errorType, e.getMessage());
            notifyStatus(SyncStatus.ERROR);
            notifyFinished(errResult);
            return errResult;

        } catch (IOException e) {
            logger.e(TAG, "Lỗi mạng hoặc Timeout (IOException): " + e.getMessage(), e);
            SyncResult errResult = SyncResult.error(SyncResult.ErrorType.NETWORK_ERROR, "Mất kết nối máy chủ: " + e.getMessage());
            notifyStatus(SyncStatus.ERROR);
            notifyFinished(errResult);
            return errResult;

        } catch (Exception e) {
            logger.e(TAG, "Lỗi logic nội bộ không xác định (INTERNAL_ERROR): " + e.getMessage(), e);
            SyncResult errResult = SyncResult.error(SyncResult.ErrorType.INTERNAL_ERROR, "Lỗi xử lý nội bộ: " + e.getMessage());
            notifyStatus(SyncStatus.ERROR);
            notifyFinished(errResult);
            return errResult;

        } finally {
            // Đảm bảo luôn reset cờ hủy và giải phóng lock đồng bộ
            isAborted.set(false);
            isSyncing.set(false);
        }
    }
}
