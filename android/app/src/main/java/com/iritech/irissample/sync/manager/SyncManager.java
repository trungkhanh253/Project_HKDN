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
                logger.e(TAG, "Lỗi khi thông báo trạng thái", e);
            }
        }
    }

    private void notifyFinished(SyncResult result) {
        this.lastResult = result;
        for (SyncListener l : listeners) {
            try {
                l.onSyncFinished(result);
            } catch (Exception e) {
                logger.e(TAG, "Lỗi khi thông báo kết quả", e);
            }
        }
    }

    public SyncStatus getCurrentStatus() {
        return currentStatus;
    }

    public SyncResult getLastResult() {
        return lastResult;
    }

    public boolean isSyncingNow() {
        return isSyncing.get();
    }

    /**
     * THỰC HIỆN CHU TRÌNH ĐỒNG BỘ 2 CHIỀU (BLOCKING METHOD)
     */
    public SyncResult sync() {
        // 1. Chống chạy trùng lặp luồng
        if (!isSyncing.compareAndSet(false, true)) {
            logger.w(TAG, "Tiến trình đồng bộ đang chạy, bỏ qua lượt gọi trùng.");
            SyncResult skipped = SyncResult.skippedConcurrent();
            notifyStatus(SyncStatus.SKIPPED);
            notifyFinished(skipped);
            return skipped;
        }

        List<String> lastAttemptedBatchIds = new ArrayList<>();

        try {
            // 2. Kiểm tra điều kiện cấu hình
            if (!prefs.isServerMode()) {
                logger.d(TAG, "Đang ở chế độ Standalone Mode, bỏ qua đồng bộ.");
                SyncResult skipped = SyncResult.skippedStandalone();
                notifyStatus(SyncStatus.SKIPPED);
                notifyFinished(skipped);
                return skipped;
            }

            String serverUrl = prefs.getServerUrl();
            String token = prefs.getAuthToken();
            if (serverUrl == null || serverUrl.trim().isEmpty() || token == null || token.trim().isEmpty()) {
                logger.w(TAG, "Chưa cấu hình URL máy chủ hoặc chưa đăng nhập (thiếu token).");
                SyncResult skipped = SyncResult.skippedNoConfig();
                notifyStatus(SyncStatus.SKIPPED);
                notifyFinished(skipped);
                return skipped;
            }

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
                // Kiểm tra Worker có bị hệ điều hành ngắt hay không
                if (Thread.currentThread().isInterrupted()) {
                    logger.w(TAG, "Sync thread bị ngắt (Worker stopped), dừng chu trình push.");
                    SyncResult interruptResult = SyncResult.error(SyncResult.ErrorType.INTERNAL_ERROR, "Tác vụ đồng bộ bị hủy ngang");
                    notifyStatus(SyncStatus.ERROR);
                    notifyFinished(interruptResult);
                    return interruptResult;
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
                }

                logger.d(TAG, "Đang push lô " + pushBatchCount + " (" + pendingChanges.size() + " bản ghi)...");

                SyncPushRequest pushRequest = new SyncPushRequest(prefs.getDeviceId(), pendingChanges);
                SyncPushResponse pushResponse = api.push(pushRequest);

                // Kiểm tra lỗi nếu response rỗng
                if (pushResponse == null) {
                    throw new SyncApiException(500, "Server trả về Push response rỗng");
                }

                List<String> syncedIds = pushResponse.getSyncedChangeIds();
                List<String> failedIds = pushResponse.getFailedChangeIds();

                // Kiểm tra tiến triển: nếu server không xác nhận bất kỳ dòng nào -> Dừng push tránh lặp vô hạn
                int handled = (syncedIds == null ? 0 : syncedIds.size()) + (failedIds == null ? 0 : failedIds.size());
                if (handled == 0) {
                    logger.w(TAG, "Lô " + pushBatchCount + ": Server không xác nhận bản ghi nào trong synced hay failed. Dừng push để bảo vệ.");
                    break;
                }

                // a. Xóa khỏi outbox các change_id server xác nhận thành công
                if (syncedIds != null && !syncedIds.isEmpty()) {
                    repository.markSynced(syncedIds);
                    totalPushed += syncedIds.size();
                    logger.d(TAG, "Lô " + pushBatchCount + ": Push thành công " + syncedIds.size() + " bản ghi.");
                }

                // b. Đánh dấu FAILED các change_id server từ chối riêng lẻ
                if (failedIds != null && !failedIds.isEmpty()) {
                    String errMsg = pushResponse.getErrorMessage() != null ? pushResponse.getErrorMessage() : "Server rejected item";
                    repository.markFailed(failedIds, errMsg);
                    totalFailed += failedIds.size();
                    logger.w(TAG, "Lô " + pushBatchCount + ": Có " + failedIds.size() + " bản ghi bị từ chối: " + errMsg);
                }

                // c. Nếu số bản ghi vừa lấy < BATCH_SIZE thì outbox đã hết, dừng lặp push
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
            long currentSeq = prefs.getLastSeq();
            int pullPageCount = 0;

            while (hasMore && pullPageCount < MAX_PULL_PAGES) {
                if (Thread.currentThread().isInterrupted()) {
                    logger.w(TAG, "Sync thread bị ngắt (Worker stopped), dừng chu trình pull.");
                    SyncResult interruptResult = SyncResult.error(SyncResult.ErrorType.INTERNAL_ERROR, "Tác vụ đồng bộ bị hủy ngang");
                    notifyStatus(SyncStatus.ERROR);
                    notifyFinished(interruptResult);
                    return interruptResult;
                }

                pullPageCount++;
                logger.d(TAG, "Đang kéo trang " + pullPageCount + " từ server (since_seq = " + currentSeq + ", limit = " + BATCH_SIZE + ")...");
                SyncPullResponse pullResponse = api.pull(currentSeq, BATCH_SIZE);

                if (pullResponse == null) {
                    throw new SyncApiException(500, "Server trả về Pull response rỗng");
                }

                List<SyncChange> changes = pullResponse.getChanges();
                long newSeq = pullResponse.getNewSeq();

                // BẢO VỆ CHỐNG VÒNG LẶP VÔ HẠN:
                // Nếu server báo has_more=true nhưng new_seq không tăng -> Ném lỗi ngay lập tức
                if (pullResponse.isHasMore() && newSeq <= currentSeq) {
                    throw new IllegalStateException("Server báo has_more=true nhưng new_seq không tăng (" + newSeq + " <= " + currentSeq + ")");
                }

                // 1. Áp dụng thay đổi vào SQLite (idempotent upsert & tự tắt trigger trong transaction)
                if (changes != null && !changes.isEmpty()) {
                    repository.applyPulledChanges(changes);
                    totalPulled += changes.size();
                    logger.d(TAG, "Trang " + pullPageCount + ": Đã cập nhật " + changes.size() + " bản ghi vào SQLite local.");
                }

                // 2. Chỉ ghi nhận last_seq mới sau khi SQLite apply thành công
                if (newSeq > currentSeq) {
                    currentSeq = newSeq;
                    prefs.setLastSeq(currentSeq);
                }

                hasMore = pullResponse.isHasMore();
            }

            if (pullPageCount >= MAX_PULL_PAGES) {
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

            // Xử lý Lô Độc: Nếu server từ chối cả request bằng lỗi 4xx client validation (400, 422)
            // thì tăng retry_count cho các bản ghi trong lô để tránh kẹt vĩnh viễn hàng đợi
            if (e.isClientValidationError() && !lastAttemptedBatchIds.isEmpty()) {
                logger.w(TAG, "Lỗi 4xx cả lô request, tăng retry_count cho " + lastAttemptedBatchIds.size() + " bản ghi trong lô.");
                repository.recordBatchFailure(lastAttemptedBatchIds, e.getMessage());
            }

            SyncResult.ErrorType errorType;
            if (e.isAuthError()) {
                errorType = SyncResult.ErrorType.AUTH_ERROR; // 401, 403: Không retry
            } else if (e.isRetryableHttp()) {
                errorType = SyncResult.ErrorType.SERVER_ERROR; // 408, 429, 5xx: Có retry
            } else {
                errorType = SyncResult.ErrorType.VALIDATION_ERROR; // 400, 404, 422: Không retry
            }

            SyncResult errResult = SyncResult.error(errorType, e.getMessage());
            notifyStatus(SyncStatus.ERROR);
            notifyFinished(errResult);
            return errResult;

        } catch (IOException e) {
            // Lỗi mạng hoặc Timeout
            logger.e(TAG, "Lỗi mạng hoặc Timeout (IOException): " + e.getMessage(), e);
            SyncResult errResult = SyncResult.error(SyncResult.ErrorType.NETWORK_ERROR, "Mất kết nối máy chủ: " + e.getMessage());
            notifyStatus(SyncStatus.ERROR);
            notifyFinished(errResult);
            return errResult;

        } catch (Exception e) {
            // Bắt các Exception logic (NPE, IllegalStateException, JsonSyntaxException, RuntimeException)
            // Ánh xạ sang INTERNAL_ERROR (Không retry) để Worker không lặp vô ích
            logger.e(TAG, "Lỗi logic nội bộ không xác định (INTERNAL_ERROR): " + e.getMessage(), e);
            SyncResult errResult = SyncResult.error(SyncResult.ErrorType.INTERNAL_ERROR, "Lỗi xử lý nội bộ: " + e.getMessage());
            notifyStatus(SyncStatus.ERROR);
            notifyFinished(errResult);
            return errResult;

        } finally {
            isSyncing.set(false); // Luôn luôn mở khóa luồng an toàn
        }
    }
}
