package com.iritech.irissample.sync.worker;

import android.app.Activity;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import com.google.gson.JsonObject;
import com.iritech.irissample.sync.api.RetrofitSyncApi;
import com.iritech.irissample.sync.api.SyncApi;
import com.iritech.irissample.sync.api.SyncApiFactory;
import com.iritech.irissample.sync.api.SyncApiService;
import com.iritech.irissample.sync.data.AndroidSyncPrefs;
import com.iritech.irissample.sync.data.ISyncPrefs;
import com.iritech.irissample.sync.data.SQLiteSyncRepository;
import com.iritech.irissample.sync.data.SyncRepository;
import com.iritech.irissample.sync.manager.SyncManager;
import com.iritech.irissample.sync.model.SyncResult;
import com.iritech.irissample.sync.util.AndroidLogger;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import retrofit2.Response;

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
            SyncApiFactory.initialize(appCtx);

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

    private static final long FOREGROUND_POLL_INTERVAL_MS = 30_000L;
    private static final Handler sMainHandler = new Handler(Looper.getMainLooper());
    private static final ExecutorService sPollExecutor = Executors.newSingleThreadExecutor();
    private static Runnable sCurrentPollTask = null;

    /**
     * Kích hoạt đồng bộ ngay nếu đang ở Server Mode và đã có JWT Token.
     */
    public static void triggerSyncIfServerMode(Context context) {
        if (context == null) return;
        AndroidSyncPrefs prefs = new AndroidSyncPrefs(context.getApplicationContext());
        String token = prefs.getAuthToken();
        if (prefs.isServerMode() && token != null && !token.trim().isEmpty()) {
            triggerImmediateSync(context.getApplicationContext());
        }
    }

    /**
     * Bắt đầu chu trình đồng bộ tự động khi màn hình đang mở (Task 21):
     * - Chạy ngay khi mở màn hình (hoặc quay lại sau khi Thêm/Sửa/Xóa).
     * - Tự động kiểm tra /api/v1/sync/status mỗi 30 giây khi màn hình đang mở.
     * - Nếu có thay đổi cục bộ (pending > 0) hoặc server có dữ liệu mới (latest_seq > last_seq),
     *   thực thi sync() và gọi onUiRefresh trên Main Thread để cập nhật danh sách SQLite lên UI.
     */
    public static void startForegroundAutoSync(final Activity activity, final Runnable onUiRefresh) {
        stopForegroundAutoSync();
        if (activity == null) return;
        final Context appCtx = activity.getApplicationContext();

        sCurrentPollTask = new Runnable() {
            @Override
            public void run() {
                if (activity.isFinishing() || activity.isDestroyed()) {
                    return;
                }
                sPollExecutor.execute(new Runnable() {
                    @Override
                    public void run() {
                        try {
                            AndroidSyncPrefs prefs = new AndroidSyncPrefs(appCtx);
                            String token = prefs.getAuthToken();
                            if (!prefs.isServerMode() || token == null || token.trim().isEmpty()) {
                                return;
                            }
                            SyncApiFactory.initialize(appCtx);
                            SQLiteSyncRepository repo = new SQLiteSyncRepository(appCtx);
                            boolean shouldSync = repo.getPendingCount() > 0 || repo.getLastSeq() == 0;

                            if (!shouldSync) {
                                try {
                                    SyncApiService service = SyncApiFactory.createService(prefs);
                                    Response<JsonObject> resp = service.getSyncStatus().execute();
                                    if (resp.isSuccessful() && resp.body() != null && resp.body().has("latest_seq")) {
                                        long latestSeq = resp.body().get("latest_seq").getAsLong();
                                        if (latestSeq > repo.getLastSeq()) {
                                            shouldSync = true;
                                        }
                                    }
                                } catch (Exception e) {
                                    Log.w(TAG, "Không thể kiểm tra /sync/status: " + e.getMessage());
                                }
                            }

                            if (shouldSync) {
                                SyncManager manager = initDefaultSyncManager(appCtx);
                                SyncResult result = manager.sync();
                                if (result != null && (result.getPushedCount() > 0 || result.getPulledCount() > 0)) {
                                    if (onUiRefresh != null && !activity.isFinishing() && !activity.isDestroyed()) {
                                        activity.runOnUiThread(onUiRefresh);
                                    }
                                }
                            }
                        } catch (Exception e) {
                            Log.w(TAG, "Lỗi trong chu trình auto-sync nền: " + e.getMessage());
                        }
                    }
                });
                sMainHandler.postDelayed(this, FOREGROUND_POLL_INTERVAL_MS);
            }
        };
        sMainHandler.post(sCurrentPollTask);
    }

    /**
     * Dừng chu trình tự động kéo 30s khi rời màn hình (onPause).
     */
    public static void stopForegroundAutoSync() {
        if (sCurrentPollTask != null) {
            sMainHandler.removeCallbacks(sCurrentPollTask);
            sCurrentPollTask = null;
        }
    }
}
