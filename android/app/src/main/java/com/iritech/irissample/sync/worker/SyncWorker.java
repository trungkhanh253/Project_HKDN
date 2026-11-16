package com.iritech.irissample.sync.worker;

import android.content.Context;
import android.util.Log;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import com.iritech.irissample.sync.manager.SyncManager;
import com.iritech.irissample.sync.model.SyncResult;

/**
 * TẦNG THỰC THI CHẠY NỀN VỚI ANDROID WORKMANAGER (SYNC WORKER)
 */
public class SyncWorker extends Worker {

    private static final String TAG = "SyncWorker";
    public static final int MAX_WORKER_RETRIES = 5;

    public enum Outcome {
        SUCCESS,
        RETRY,
        FAILURE
    }

    public SyncWorker(@NonNull Context context, @NonNull WorkerParameters workerParams) {
        super(context, workerParams);
    }

    /**
     * Hàm thuần túy (Pure Function) quyết định kết quả WorkManager
     * Tách biệt logic để dễ dàng viết Unit Test trên JVM mà không cần môi trường Android.
     */
    public static Outcome decideOutcome(SyncResult result, int runAttemptCount) {
        if (result == null || result.isSuccess() || result.isSkipped()) {
            return Outcome.SUCCESS;
        }

        if (result.isRetryable()) {
            if (runAttemptCount >= MAX_WORKER_RETRIES) {
                return Outcome.FAILURE;
            }
            return Outcome.RETRY;
        }

        // AUTH_ERROR, VALIDATION_ERROR, INTERNAL_ERROR
        return Outcome.FAILURE;
    }

    @NonNull
    @Override
    public Result doWork() {
        Log.d(TAG, "SyncWorker.doWork() đang chạy trên background thread... (Lần thử: " + getRunAttemptCount() + ")");

        SyncManager syncManager;
        try {
            syncManager = SyncManager.getInstance();
        } catch (IllegalStateException e) {
            Log.w(TAG, "SyncManager chưa được Application khởi tạo, tự động khởi tạo mặc định...");
            try {
                syncManager = SyncWorkScheduler.initDefaultSyncManager(getApplicationContext());
            } catch (Exception initEx) {
                Log.e(TAG, "Không thể khởi tạo SyncManager mặc định: " + initEx.getMessage());
                return Result.failure();
            }
        }

        // Thực thi chu trình Push -> Pull (Blocking trên luồng nền của WorkManager)
        SyncResult result = syncManager.sync();
        Log.d(TAG, "SyncWorker kết quả: " + result);

        Outcome outcome = decideOutcome(result, getRunAttemptCount());
        switch (outcome) {
            case SUCCESS:
                return Result.success();
            case RETRY:
                Log.d(TAG, "SyncWorker yêu cầu WorkManager lên lịch thử lại (Exponential Backoff)...");
                return Result.retry();
            case FAILURE:
            default:
                Log.w(TAG, "SyncWorker kết thúc dạng Failure (" + result.getErrorType() + ").");
                return Result.failure();
        }
    }

    @Override
    public void onStopped() {
        super.onStopped();
        Log.w(TAG, "SyncWorker bị hệ điều hành dừng (onStopped). Yêu cầu SyncManager hủy chu trình đang chạy dở...");
        SyncManager m = SyncManager.getInstanceOrNull();
        if (m != null) {
            m.abortCurrentSync();
        }
    }
}
