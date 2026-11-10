package com.iritech.irissample.sync.worker;

import android.content.Context;
import android.util.Log;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import com.iritech.irissample.sync.api.RetrofitSyncApi;
import com.iritech.irissample.sync.api.SyncApi;
import com.iritech.irissample.sync.data.AndroidSyncPrefs;
import com.iritech.irissample.sync.data.ISyncPrefs;
import com.iritech.irissample.sync.data.SQLiteSyncRepository;
import com.iritech.irissample.sync.data.SyncRepository;
import com.iritech.irissample.sync.manager.SyncManager;
import com.iritech.irissample.sync.util.AndroidLogger;
import java.util.concurrent.TimeUnit;

/**
 * Tiện ích điều phối lịch trình WorkManager cho ứng dụng
 * Đảm bảo:
 * 1. Định kỳ 15 phút, constraint có mạng (NetworkType.CONNECTED), KEEP tránh trùng lịch.
 * 2. Backoff Exponential 30s khi lỗi có thể thử lại (Network, Server).
 * 3. Sync tay dùng OneTimeWorkRequest với APPEND_OR_REPLACE, KHÔNG BAO GIỜ gọi sync() trên Main Thread.
 * 4. cancelAllSync() an toàn, không ném exception nếu SyncManager/WorkManager chưa khởi tạo.
 */
public class SyncWorkScheduler {

    private static final String TAG = "SyncWorkScheduler";
    public static final String PERIODIC_WORK_NAME = "AttendancePeriodicSyncWork";
    public static final String ONE_TIME_WORK_NAME = "AttendanceImmediateSyncWork";

    private static SyncRepository sCustomRepository = null;

    /**
     * Cho phép cấu hình SyncRepository (Chỉ dùng cho Unit Test hoặc Mocking).
     * Khi Android 1 hoàn tất SqliteSyncRepository, repo thật sẽ được gắn vào initDefaultSyncManager.
     */
    @androidx.annotation.VisibleForTesting
    public static synchronized void setCustomRepository(SyncRepository repository) {
        sCustomRepository = repository;
    }

    /**
     * Khởi tạo SyncManager mặc định (Fallback an toàn khi WorkManager chạy sau khi hệ thống boot)
     * Đồng bộ hóa (synchronized) để chống race condition giữa PeriodicWorker và OneTimeWorker.
     */
    public static synchronized SyncManager initDefaultSyncManager(Context context) {
        try {
            return SyncManager.getInstance();

        } catch (IllegalStateException ignored) {

            Context appCtx = context.getApplicationContext();

            // 1. Đọc cấu hình Server Mode, URL và JWT
            ISyncPrefs prefs = new AndroidSyncPrefs(appCtx);

            // 2. Khởi tạo API Flask
            SyncApi api = new RetrofitSyncApi(prefs);

            // 3. Sử dụng SQLiteSyncRepository thật
            SyncRepository repo = sCustomRepository;

            if (repo == null) {
                repo = new SQLiteSyncRepository(appCtx);
            }

            // 4. Khởi tạo SyncManager
            SyncManager manager = new SyncManager(
                    api,
                    repo,
                    prefs,
                    new AndroidLogger()
            );

            // 5. Lưu instance dùng chung
            SyncManager.initialize(manager);

            Log.d(TAG, "Đã khởi tạo SyncManager với SQLiteSyncRepository thành công.");

            return manager;
        }
    }

    /**
     * BẬT LỊCH ĐỒNG BỘ ĐỊNH KỲ (15 phút/lần, ràng buộc CÓ MẠNG)
     * Sử dụng ExistingPeriodicWorkPolicy.KEEP để nếu đã có lịch thì giữ nguyên, không tạo trùng.
     * Backoff Exponential 30s cho các lần retry.
     */
    public static void schedulePeriodicSync(Context context) {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();

        PeriodicWorkRequest periodicRequest = new PeriodicWorkRequest.Builder(
                SyncWorker.class, 15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build();

        WorkManager.getInstance(context.getApplicationContext()).enqueueUniquePeriodicWork(
                PERIODIC_WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                periodicRequest
        );

        Log.d(TAG, "Đã lên lịch đồng bộ định kỳ 15 phút/lần (Chỉ chạy khi có mạng, Backoff 30s).");
    }

    /**
     * KÍCH HOẠT ĐỒNG BỘ TAY (SYNC NGAY)
     * Chạy trên luồng nền của WorkManager bằng OneTimeWorkRequest, TUYỆT ĐỐI không block Main Thread.
     * Sử dụng ExistingWorkPolicy.APPEND_OR_REPLACE để không làm gián đoạn lượt sync đang diễn ra.
     */
    public static void triggerImmediateSync(Context context) {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();

        OneTimeWorkRequest oneTimeRequest = new OneTimeWorkRequest.Builder(SyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build();

        WorkManager.getInstance(context.getApplicationContext()).enqueueUniqueWork(
                ONE_TIME_WORK_NAME,
                ExistingWorkPolicy.APPEND_OR_REPLACE,
                oneTimeRequest
        );

        Log.d(TAG, "Đã kích hoạt yêu cầu đồng bộ ngay (OneTimeWorkRequest, APPEND_OR_REPLACE, Backoff 30s).");
    }

    /**
     * HỦY TOÀN BỘ TIẾN TRÌNH ĐỒNG BỘ VÀ ABORT TIẾN TRÌNH HIỆN TẠI
     * Gọi khi người dùng chuyển sang Standalone Mode hoặc đăng xuất.
     * An toàn tuyệt đối không gây crash nếu SyncManager chưa được khởi tạo.
     */
    public static void cancelAllSync(Context context) {
        if (context != null) {
            try {
                WorkManager wm = WorkManager.getInstance(context.getApplicationContext());
                wm.cancelUniqueWork(PERIODIC_WORK_NAME);
                wm.cancelUniqueWork(ONE_TIME_WORK_NAME);
            } catch (Exception e) {
                Log.w(TAG, "WorkManager chưa sẵn sàng hoặc không thể hủy: " + e.getMessage());
            }
        }

        SyncManager m = SyncManager.getInstanceOrNull();
        if (m != null) {
            m.abortCurrentSync();
        }

        Log.d(TAG, "Đã hủy toàn bộ tác vụ đồng bộ và gửi cờ abortCurrentSync().");
    }
}
