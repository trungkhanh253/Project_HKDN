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
 * BỘ NÃO ĐIỀU PHỐI ĐỒNG BỘ (SYNC MANAGER) - BẢN SẢN XUẤT (PRODUCTION GRADE)
 *
 * Đã xử lý triệt để 100% các góc khuất:
 * 1. Chống chạy trùng lặp (AtomicBoolean isSyncing) - LUÔN mở khóa trong finally.
 * 2. Push nhiều lô (Batching Loop) - Đẩy sạch outbox (tối đa 20 lô = 2000 bản ghi/lần).
 * 3. Chống kẹt outbox & bảo vệ dữ liệu khi mất mạng (chỉ markFailed khi server từ chối cụ thể).
 * 4. Chống lặp vô hạn khi Pull (Guard: new_seq không tăng hoặc vượt quá MAX_PULL_PAGES 50 trang).
 * 5. Tính nguyên tử: Chỉ cập nhật last_seq sau khi trang pull tương ứng ghi SQLite thành công.
 * 6. UI Thread Safety: Dùng CopyOnWriteArrayList cho listeners, không làm crash JVM test.
 */
public class SyncManager {

    private static final String TAG = "SyncManager";
    public static final int BATCH_SIZE = 100;
    public static final int MAX_PUSH_BATCHES = 20; // Tối đa đẩy 20 lô (2000 dòng) mỗi lần sync
    public static final int MAX_PULL_PAGES = 50;    // Tối đa kéo 50 trang mỗi lần sync để chống lặp vô hạn

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
     * Toàn bộ phương thức được bảo vệ an toàn: isSyncing LUÔN được giải phóng trong finally.
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
            // BƯỚC 1: PUSH NHIỀU LÔ (Xử lý sạch outbox, tối đa MAX_PUSH_BATCHES lô)
            // -------------------------------------------------------------------------
            int pushBatchCount = 0;
            boolean hasMorePending = true;

            while (hasMorePending && pushBatchCount < MAX_PUSH_BATCHES) {
                List<SyncChange> pendingChanges = repository.getPendingChanges(BATCH_SIZE);
                if (pendingChanges == null || pendingChanges.isEmpty()) {
                    hasMorePending = false;
                    break;
                }

                pushBatchCount++;
                logger.d(TAG, "Đang push lô " + pushBatchCount + " (" + pendingChanges.size() + " bản ghi)...");

                SyncPushRequest pushRequest = new SyncPushRequest(prefs.getDeviceId(), pendingChanges);
                SyncPushResponse pushResponse = api.push(pushRequest);

                if (pushResponse != null) {
                    // a. Chỉ xóa khỏi outbox các change_id server xác nhận thành công
                    List<String> syncedIds = pushResponse.getSyncedChangeIds();
                    if (syncedIds != null && !syncedIds.isEmpty()) {
                        repository.markSynced(syncedIds);
                        totalPushed += syncedIds.size();
                        logger.d(TAG, "Lô " + pushBatchCount + ": Push thành công " + syncedIds.size() + " bản ghi.");
                    }

                    // b. Chỉ đánh dấu FAILED các change_id server từ chối riêng lẻ
                    List<String> failedIds = pushResponse.getFailedChangeIds();
                    if (failedIds != null && !failedIds.isEmpty()) {
                        String errMsg = pushResponse.getErrorMessage() != null ? pushResponse.getErrorMessage() : "Server rejected item";
                        repository.markFailed(failedIds, errMsg);
                        logger.w(TAG, "Lô " + pushBatchCount + ": Có " + failedIds.size() + " bản ghi bị từ chối: " + errMsg);
                    }

                    // c. Kiểm tra nếu số bản ghi còn lại trong outbox < BATCH_SIZE thì dừng lặp push
                    if (pendingChanges.size() < BATCH_SIZE) {
                        hasMorePending = false;
                    }
                } else {
                    hasMorePending = false;
                }
            }

            // -------------------------------------------------------------------------
            // BƯỚC 2: PULL VỚI PHÂN TRANG (Kéo dữ liệu mới từ Server về SQLite)
            // CÓ CƠ CHẾ BẢO VỆ CHỐNG LẶP VÔ HẠN
            // -------------------------------------------------------------------------
            boolean hasMore = true;
            long currentSeq = prefs.getLastSeq();
            int pullPageCount = 0;

            while (hasMore && pullPageCount < MAX_PULL_PAGES) {
                pullPageCount++;
                logger.d(TAG, "Đang kéo trang " + pullPageCount + " từ server (since_seq = " + currentSeq + ", limit = " + BATCH_SIZE + ")...");
                SyncPullResponse pullResponse = api.pull(currentSeq, BATCH_SIZE);

                if (pullResponse != null) {
                    List<SyncChange> changes = pullResponse.getChanges();
                    long newSeq = pullResponse.getNewSeq();

                    // BẢO VỆ CHỐNG VÒNG LẶP VÔ HẠN:
                    // Nếu server báo has_more=true nhưng new_seq không tăng VÀ không có bản ghi mới -> DỪNG NGAY
                    if (pullResponse.isHasMore() && newSeq <= currentSeq && (changes == null || changes.isEmpty())) {
                        logger.w(TAG, "Cảnh báo: Server báo has_more=true nhưng new_seq không tăng (" + newSeq + " <= " + currentSeq + "). Dừng vòng lặp pull để bảo vệ.");
                        break;
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
                } else {
                    hasMore = false;
                }
            }

            if (pullPageCount >= MAX_PULL_PAGES) {
                logger.w(TAG, "Đã chạm giới hạn tối đa " + MAX_PULL_PAGES + " trang pull trong một lần sync.");
            }

            // -------------------------------------------------------------------------
            // BƯỚC 3: HOÀN TẤT THÀNH CÔNG
            // -------------------------------------------------------------------------
            prefs.setLastSyncTime(System.currentTimeMillis());
            SyncResult successResult = SyncResult.success(totalPushed, totalPulled);

            logger.d(TAG, "Đồng bộ hoàn tất thành công! Pushed: " + totalPushed + ", Pulled: " + totalPulled);
            notifyStatus(SyncStatus.SUCCESS);
            notifyFinished(successResult);
            return successResult;

        } catch (SyncApiException e) {
            // Lỗi từ Server trả về qua HTTP code
            logger.e(TAG, "Lỗi SyncApiException (HTTP " + e.getHttpCode() + "): " + e.getMessage(), e);
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
            // Lỗi mạng, đứt cáp, timeout
            logger.e(TAG, "Lỗi mạng hoặc Timeout (IOException): " + e.getMessage(), e);
            SyncResult errResult = SyncResult.error(SyncResult.ErrorType.NETWORK_ERROR, "Mất kết nối máy chủ: " + e.getMessage());
            notifyStatus(SyncStatus.ERROR);
            notifyFinished(errResult);
            return errResult;

        } catch (Throwable t) {
            // Bắt toàn bộ lỗi còn lại (kể cả RuntimeException, JsonSyntaxException, OOM)
            logger.e(TAG, "Lỗi nghiêm trọng không xác định trong sync(): " + t.getMessage(), t);
            SyncResult errResult = SyncResult.error(SyncResult.ErrorType.SERVER_ERROR, "Lỗi xử lý nội bộ: " + t.getMessage());
            notifyStatus(SyncStatus.ERROR);
            notifyFinished(errResult);
            return errResult;

        } finally {
            // BẢO ĐẢM 100%: Luôn luôn mở khóa luồng kể cả khi ném Exception bất ngờ
            isSyncing.set(false);
        }
    }
}
