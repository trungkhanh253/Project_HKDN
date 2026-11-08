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
 * BỘ NÃO ĐIỀU PHỐI ĐỒNG BỘ (SYNC MANAGER)
 *
 * Chịu trách nhiệm:
 * 1. Chống chạy trùng lặp (Concurrency Lock bằng AtomicBoolean).
 * 2. Kiểm tra điều kiện tiên quyết (Server Mode, URL, Token).
 * 3. Chu trình Push trước -> Pull sau (Push lỗi thì dừng, không kéo Pull để tránh ghi đè).
 * 4. Phân trang khi Pull (lặp lại cho đến khi has_more == false).
 * 5. Cập nhật last_seq an toàn sau mỗi trang SQLite apply thành công.
 * 6. Thông báo trạng thái ra ngoài qua Callback / Listener (hỗ trợ cả UI Android lẫn JVM Test).
 */
public class SyncManager {

    private static final String TAG = "SyncManager";
    private static final int BATCH_SIZE = 100;

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
            // Gửi trạng thái hiện tại ngay khi đăng ký
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

    /**
     * THỰC HIỆN CHU TRÌNH ĐỒNG BỘ 2 CHIỀU (BLOCKING METHOD)
     * Thường được gọi bên trong luồng nền của SyncWorker hoặc Thread riêng.
     */
    public SyncResult sync() {
        // 1. Chống chạy trùng lặp luồng
        if (!isSyncing.compareAndSet(false, true)) {
            logger.w(TAG, "Tiến trình đồng bộ đang chạy, bỏ qua lượt gọi trùng.");
            SyncResult skipped = SyncResult.skippedConcurrent();
            notifyFinished(skipped);
            return skipped;
        }

        try {
            // 2. Kiểm tra điều kiện cấu hình
            if (!prefs.isServerMode()) {
                logger.d(TAG, "Đang ở chế độ Standalone Mode, bỏ qua đồng bộ.");
                SyncResult skipped = SyncResult.skippedNoConfig();
                notifyFinished(skipped);
                return skipped;
            }

            String serverUrl = prefs.getServerUrl();
            String token = prefs.getAuthToken();
            if (serverUrl == null || serverUrl.trim().isEmpty() || token == null || token.trim().isEmpty()) {
                logger.w(TAG, "Chưa cấu hình URL máy chủ hoặc chưa đăng nhập (thiếu token).");
                SyncResult skipped = SyncResult.skippedNoConfig();
                notifyFinished(skipped);
                return skipped;
            }

            notifyStatus(SyncStatus.SYNCING);
            logger.d(TAG, "Bắt đầu chu trình đồng bộ: PUSH -> PULL...");

            int totalPushed = 0;
            int totalPulled = 0;

            // -------------------------------------------------------------------------
            // BƯỚC 1: PUSH (Đẩy các thay đổi đang chờ trong SQLite outbox lên Server)
            // -------------------------------------------------------------------------
            List<SyncChange> pendingChanges = repository.getPendingChanges(BATCH_SIZE);
            if (pendingChanges != null && !pendingChanges.isEmpty()) {
                logger.d(TAG, "Tìm thấy " + pendingChanges.size() + " bản ghi outbox đang chờ push.");

                SyncPushRequest pushRequest = new SyncPushRequest(prefs.getDeviceId(), pendingChanges);
                SyncPushResponse pushResponse = api.push(pushRequest);

                if (pushResponse != null) {
                    List<String> syncedIds = pushResponse.getSyncedChangeIds();
                    if (syncedIds != null && !syncedIds.isEmpty()) {
                        repository.markSynced(syncedIds);
                        totalPushed = syncedIds.size();
                        logger.d(TAG, "Đã push thành công " + totalPushed + " bản ghi (đã xóa khỏi outbox).");
                    }

                    List<String> failedIds = pushResponse.getFailedChangeIds();
                    if (failedIds != null && !failedIds.isEmpty()) {
                        String errMsg = pushResponse.getErrorMessage() != null ? pushResponse.getErrorMessage() : "Server rejected item";
                        repository.markFailed(failedIds, errMsg);
                        logger.w(TAG, "Có " + failedIds.size() + " bản ghi bị server từ chối: " + errMsg);
                    }
                }
            } else {
                logger.d(TAG, "Outbox rỗng, không có thay đổi nào cần push. Tiến hành Pull.");
            }

            // -------------------------------------------------------------------------
            // BƯỚC 2: PULL (Kéo các thay đổi mới từ Server về SQLite cục bộ với Phân trang)
            // -------------------------------------------------------------------------
            boolean hasMore = true;
            long currentSeq = prefs.getLastSeq();

            while (hasMore) {
                logger.d(TAG, "Đang kéo dữ liệu từ server (since_seq = " + currentSeq + ", limit = " + BATCH_SIZE + ")...");
                SyncPullResponse pullResponse = api.pull(currentSeq, BATCH_SIZE);

                if (pullResponse != null) {
                    List<SyncChange> changes = pullResponse.getChanges();
                    if (changes != null && !changes.isEmpty()) {
                        // 1. Áp dụng thay đổi vào SQLite (tự động tắt trigger trong khối transaction try...finally)
                        repository.applyPulledChanges(changes);
                        totalPulled += changes.size();
                        logger.d(TAG, "Đã cập nhật " + changes.size() + " bản ghi vào SQLite local.");
                    }

                    // 2. Chỉ cập nhật last_seq sau khi applyPulledChanges thành công
                    currentSeq = pullResponse.getNewSeq();
                    prefs.setLastSeq(currentSeq);

                    hasMore = pullResponse.isHasMore();
                } else {
                    hasMore = false;
                }
            }

            // -------------------------------------------------------------------------
            // BƯỚC 3: HOÀN TẤT THÀNH CÔNG
            // -------------------------------------------------------------------------
            prefs.setLastSyncTime(System.currentTimeMillis());
            SyncResult successResult = SyncResult.success(totalPushed, totalPulled);

            logger.d(TAG, "Đồng bộ hoàn tất mỹ mãn! Pushed: " + totalPushed + ", Pulled: " + totalPulled);
            notifyStatus(SyncStatus.SUCCESS);
            notifyFinished(successResult);
            return successResult;

        } catch (SyncApiException e) {
            logger.e(TAG, "Lỗi SyncApiException (HTTP " + e.getHttpCode() + "): " + e.getMessage(), e);
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
            logger.e(TAG, "Lỗi không xác định trong quá trình đồng bộ: " + e.getMessage(), e);
            SyncResult errResult = SyncResult.error(SyncResult.ErrorType.SERVER_ERROR, "Lỗi hệ thống: " + e.getMessage());
            notifyStatus(SyncStatus.ERROR);
            notifyFinished(errResult);
            return errResult;

        } finally {
            isSyncing.set(false); // Luôn mở khóa để lượt sync tiếp theo có thể chạy
        }
    }
}
