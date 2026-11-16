package com.iritech.irissample.sync;

import com.google.gson.JsonObject;
import com.iritech.irissample.sync.api.MockSyncApi;
import com.iritech.irissample.sync.api.SyncApiException;
import com.iritech.irissample.sync.data.FakeSyncRepository;
import com.iritech.irissample.sync.data.InMemorySyncPrefs;
import com.iritech.irissample.sync.manager.SyncManager;
import com.iritech.irissample.sync.model.SyncChange;
import com.iritech.irissample.sync.model.SyncPullResponse;
import com.iritech.irissample.sync.model.SyncPushRequest;
import com.iritech.irissample.sync.model.SyncPushResponse;
import com.iritech.irissample.sync.model.SyncResult;
import com.iritech.irissample.sync.model.SyncStatus;
import com.iritech.irissample.sync.util.SyncLogger;

import org.junit.Before;
import org.junit.Test;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import com.iritech.irissample.sync.api.SyncApi;
import com.iritech.irissample.sync.worker.SyncWorkScheduler;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * BỘ KIỂM THỬ ĐỘC LẬP CHO BỘ NÃO ĐỒNG BỘ (SYNC MANAGER UNIT TESTS)
 * Bao phủ 100% các ca biên (Edge cases) và rủi ro logic đã thảo luận.
 */
public class SyncManagerTest {

    private MockSyncApi mockApi;
    private FakeSyncRepository fakeRepo;
    private InMemorySyncPrefs inMemoryPrefs;
    private SyncLogger logger;
    private SyncManager syncManager;

    @Before
    public void setUp() {
        mockApi = new MockSyncApi();
        fakeRepo = new FakeSyncRepository();
        inMemoryPrefs = new InMemorySyncPrefs();
        logger = new SyncLogger.ConsoleLogger();

        inMemoryPrefs.setServerMode(true);
        inMemoryPrefs.setServerUrl("http://127.0.0.1:5000");
        inMemoryPrefs.setAuthToken("test_bearer_token");
        inMemoryPrefs.setLastSeq(0L);
        fakeRepo.setLastSeq(0L);

        syncManager = new SyncManager(mockApi, fakeRepo, inMemoryPrefs, logger);
    }

    private SyncChange createSampleChange(String changeId, String uuid, String table, String op) {
        JsonObject payload = new JsonObject();
        payload.addProperty("id", uuid);
        payload.addProperty("name", "Test Item " + uuid);
        return new SyncChange(changeId, uuid, table, op, payload, System.currentTimeMillis());
    }

    // ---------------------------------------------------------------------------------
    // TEST 1: Đồng bộ bình thường (Push thành công, Pull có dữ liệu, last_seq tăng)
    // ---------------------------------------------------------------------------------
    @Test
    public void test_SyncSuccess_NormalPushAndPull() {
        fakeRepo.addPendingChange(createSampleChange("cid_1", "uuid_1", "students", "INSERT"));
        fakeRepo.addPendingChange(createSampleChange("cid_2", "uuid_2", "subjects", "INSERT"));
        assertEquals(2, fakeRepo.getPendingCount());

        mockApi.setScenario(MockSyncApi.Scenario.SUCCESS);
        mockApi.setMockServerNewSeq(105L);

        SyncResult result = syncManager.sync();

        assertTrue(result.isSuccess());
        assertEquals(SyncStatus.SUCCESS, result.getStatus());
        assertEquals(2, result.getPushedCount());
        assertEquals(1, result.getPulledCount());
        assertEquals(0, result.getFailedCount());

        assertEquals(0, fakeRepo.getPendingCount());
        assertEquals(105L, fakeRepo.getLastSeq());
        assertEquals(105L, inMemoryPrefs.getLastSeq());
    }

    // ---------------------------------------------------------------------------------
    // TEST 2: Đang ở Standalone Mode -> Phải trả về SKIPPED_STANDALONE, không gọi API
    // ---------------------------------------------------------------------------------
    @Test
    public void test_StandaloneMode_ShouldReturnSkippedStandalone() {
        inMemoryPrefs.setServerMode(false);

        fakeRepo.addPendingChange(createSampleChange("cid_1", "uuid_1", "students", "INSERT"));

        SyncResult result = syncManager.sync();

        assertTrue(result.isSkipped());
        assertEquals(SyncResult.ErrorType.SKIPPED_STANDALONE, result.getErrorType());
        assertEquals(0, mockApi.getPushCallCount());
        assertEquals(0, mockApi.getPullCallCount());
        assertEquals(1, fakeRepo.getPendingCount());
    }

    // ---------------------------------------------------------------------------------
    // TEST 3: Thiếu Server URL hoặc Token -> Phải trả về SKIPPED_NO_CONFIG, không gọi API
    // ---------------------------------------------------------------------------------
    @Test
    public void test_MissingServerUrlOrToken_ShouldReturnSkippedNoConfig() {
        inMemoryPrefs.setAuthToken("");

        SyncResult result = syncManager.sync();

        assertTrue(result.isSkipped());
        assertEquals(SyncResult.ErrorType.SKIPPED_NO_CONFIG, result.getErrorType());
        assertEquals(0, mockApi.getPushCallCount());
    }

    // ---------------------------------------------------------------------------------
    // TEST 4: Push bị 401 Unauthorized -> Dừng ngay, KHÔNG Pull, isRetryable == false
    // ---------------------------------------------------------------------------------
    @Test
    public void test_Push401Unauthorized_ShouldNotPullAndReturnAuthError() {
        fakeRepo.addPendingChange(createSampleChange("cid_1", "uuid_1", "students", "INSERT"));
        mockApi.setScenario(MockSyncApi.Scenario.HTTP_401_UNAUTHORIZED);

        SyncResult result = syncManager.sync();

        assertFalse(result.isSuccess());
        assertEquals(SyncResult.ErrorType.AUTH_ERROR, result.getErrorType());
        assertFalse(result.isRetryable());
        assertEquals(0, mockApi.getPullCallCount());
        assertEquals(1, fakeRepo.getPendingCount());
    }

    // ---------------------------------------------------------------------------------
    // TEST 5: Push bị mất mạng (IOException) -> Các dòng PHẢI GIỮ NGUYÊN PENDING, không dòng nào sang FAILED
    // ---------------------------------------------------------------------------------
    @Test
    public void test_PushNetworkError_ShouldKeepAllItemsPendingWithoutFailingAny() {
        fakeRepo.addPendingChange(createSampleChange("cid_1", "uuid_1", "students", "INSERT"));
        fakeRepo.addPendingChange(createSampleChange("cid_2", "uuid_2", "students", "INSERT"));
        mockApi.setScenario(MockSyncApi.Scenario.NETWORK_ERROR);

        SyncResult result = syncManager.sync();

        assertFalse(result.isSuccess());
        assertEquals(SyncResult.ErrorType.NETWORK_ERROR, result.getErrorType());
        assertTrue(result.isRetryable());
        assertEquals(0, mockApi.getPullCallCount());

        // CẢ 2 BẢN GHI PHẢI CÒN NGUYÊN PENDING, KHÔNG DÒNG NÀO BỊ ĐỔI THÀNH FAILED
        assertEquals(2, fakeRepo.getPendingCount());
        assertEquals(0, fakeRepo.getFailedCount());
    }

    // ---------------------------------------------------------------------------------
    // TEST 6: Push một phần (Partial Success) -> Chỉ xóa ID thành công, ID lỗi sang FAILED
    // ---------------------------------------------------------------------------------
    @Test
    public void test_PushPartialSuccess_ShouldOnlyMarkSyncedSuccessfulIds() {
        fakeRepo.addPendingChange(createSampleChange("cid_0", "uuid_0", "students", "INSERT"));
        fakeRepo.addPendingChange(createSampleChange("cid_1", "uuid_1", "students", "INSERT"));
        fakeRepo.addPendingChange(createSampleChange("cid_2", "uuid_2", "students", "INSERT"));
        fakeRepo.addPendingChange(createSampleChange("cid_3", "uuid_3", "students", "INSERT"));

        mockApi.setScenario(MockSyncApi.Scenario.PUSH_PARTIAL_SUCCESS);

        SyncResult result = syncManager.sync();

        assertTrue(result.isSuccess());
        assertEquals(2, result.getPushedCount());
        assertEquals(2, result.getFailedCount());
        assertEquals(0, fakeRepo.getPendingCount());
        assertEquals(2, fakeRepo.getFailedCount());
    }

    // ---------------------------------------------------------------------------------
    // TEST 7: Toàn bộ lô bị từ chối -> Chuyển FAILED, không làm nghẽn hàng đợi
    // ---------------------------------------------------------------------------------
    @Test
    public void test_PushAllRejected_ShouldMarkAllFailedAndNotStallQueue() {
        fakeRepo.addPendingChange(createSampleChange("cid_1", "uuid_1", "students", "INSERT"));
        fakeRepo.addPendingChange(createSampleChange("cid_2", "uuid_2", "students", "INSERT"));

        mockApi.setScenario(MockSyncApi.Scenario.PUSH_ALL_REJECTED);

        SyncResult result = syncManager.sync();

        assertEquals(0, result.getPushedCount());
        assertEquals(2, result.getFailedCount());
        assertEquals(0, fakeRepo.getPendingCount());
        assertEquals(2, fakeRepo.getFailedCount());
    }

    // ---------------------------------------------------------------------------------
    // TEST 8: Push nhiều lô (250 bản ghi) -> Phải đi hết qua 3 lô (100 + 100 + 50)
    // ---------------------------------------------------------------------------------
    @Test
    public void test_PushMultipleBatches_ShouldPushAllInBatches() {
        for (int i = 0; i < 250; i++) {
            fakeRepo.addPendingChange(createSampleChange("cid_" + i, "uuid_" + i, "checkin_history", "INSERT"));
        }
        assertEquals(250, fakeRepo.getPendingCount());

        mockApi.setScenario(MockSyncApi.Scenario.SUCCESS);

        SyncResult result = syncManager.sync();

        assertTrue(result.isSuccess());
        assertEquals(250, result.getPushedCount());
        assertEquals(3, mockApi.getPushCallCount());
        assertEquals(0, fakeRepo.getPendingCount());
    }

    // ---------------------------------------------------------------------------------
    // TEST 9: Lô "độc" (422 Client Validation Error cả request) -> Sau 5 lần retry chuyển FAILED, giải phóng hàng đợi
    // ---------------------------------------------------------------------------------
    @Test
    public void test_PoisonBatch_422ClientValidationError_ShouldIncreaseRetryAndEventuallyFail() {
        // Lô độc chứa bản ghi gây lỗi 422
        fakeRepo.addPendingChange(createSampleChange("cid_poison", "uuid_poison", "students", "INSERT"));

        SyncManager poisonManager = new SyncManager(
                new MockSyncApi() {
                    @Override
                    public SyncPushResponse push(SyncPushRequest request) throws Exception {
                        for (SyncChange c : request.getChanges()) {
                            if ("uuid_poison".equals(c.getUuid())) {
                                throw new SyncApiException(422, "Unprocessable Entity: Malformed student schema");
                            }
                        }
                        List<String> synced = new ArrayList<>();
                        for (SyncChange c : request.getChanges()) {
                            synced.add(c.getChangeId());
                        }
                        return new SyncPushResponse(true, synced, new ArrayList<>(), null);
                    }
                },
                fakeRepo, inMemoryPrefs, logger
        );

        // Chạy sync 5 lần để bản ghi poison tích lũy retry_count >= 5 và chuyển sang FAILED
        for (int i = 0; i < 5; i++) {
            SyncResult res = poisonManager.sync();
            assertFalse(res.isSuccess());
            assertEquals(SyncResult.ErrorType.VALIDATION_ERROR, res.getErrorType());
        }

        // Sau 5 lần, bản ghi poison phải được chuyển sang FAILED
        assertEquals(1, fakeRepo.getFailedCount());
        assertEquals(0, fakeRepo.getPendingCount()); // Hàng đợi đã sạch dòng PENDING

        // Bây giờ thêm bản ghi tốt vào outbox:
        fakeRepo.addPendingChange(createSampleChange("cid_good", "uuid_good", "students", "INSERT"));
        assertEquals(1, fakeRepo.getPendingCount());

        // Lần sync tiếp theo: Hàng đợi không còn bị nghẽn nữa! Bản ghi tốt được gửi đi thành công!
        SyncResult res6 = poisonManager.sync();
        assertTrue(res6.isSuccess());
        assertEquals(1, res6.getPushedCount());
        assertEquals(0, fakeRepo.getPendingCount());
    }

    // ---------------------------------------------------------------------------------
    // TEST 10: Response Push hoặc Pull null -> Phải trả về SERVER_ERROR, không báo success(0,0) giả tạo
    // ---------------------------------------------------------------------------------
    @Test
    public void test_NullPushAndPullResponse_ShouldReturnServerError() {
        fakeRepo.addPendingChange(createSampleChange("cid_1", "uuid_1", "students", "INSERT"));

        // Push null
        SyncManager nullPushManager = new SyncManager(
                new MockSyncApi() {
                    @Override
                    public SyncPushResponse push(SyncPushRequest request) { return null; }
                },
                fakeRepo, inMemoryPrefs, logger
        );
        SyncResult pushRes = nullPushManager.sync();
        assertFalse(pushRes.isSuccess());
        assertEquals(SyncResult.ErrorType.SERVER_ERROR, pushRes.getErrorType());

        // Pull null
        fakeRepo.markSynced(Collections.singletonList("cid_1")); // Dọn outbox để qua bước pull
        SyncManager nullPullManager = new SyncManager(
                new MockSyncApi() {
                    @Override
                    public SyncPullResponse pull(long sinceSeq, int limit) { return null; }
                },
                fakeRepo, inMemoryPrefs, logger
        );
        SyncResult pullRes = nullPullManager.sync();
        assertFalse(pullRes.isSuccess());
        assertEquals(SyncResult.ErrorType.SERVER_ERROR, pullRes.getErrorType());
    }

    // ---------------------------------------------------------------------------------
    // TEST 11: Apply lỗi giữa trang 2 -> last_seq phải dừng ở cuối trang 1
    // ---------------------------------------------------------------------------------
    @Test
    public void test_ApplyFailureInPage2_ShouldKeepSeqAtEndOfPage1() {
        SyncManager pageFailManager = new SyncManager(
                new MockSyncApi() {
                    private int page = 0;
                    @Override
                    public SyncPullResponse pull(long sinceSeq, int limit) {
                        page++;
                        if (page == 1) {
                            SyncChange c1 = createSampleChange("cid_p1", "uuid_p1", "students", "INSERT");
                            return new SyncPullResponse(50L, true, Collections.singletonList(c1));
                        } else {
                            SyncChange c2 = createSampleChange("cid_p2", "uuid_p2", "students", "INSERT");
                            return new SyncPullResponse(100L, false, Collections.singletonList(c2));
                        }
                    }
                },
                new FakeSyncRepository() {
                    private int callCount = 0;
                    @Override
                    public synchronized void applyPulledChanges(List<SyncChange> changes, long newSeq) {
                        callCount++;
                        if (callCount == 1) {
                            super.applyPulledChanges(changes, newSeq); // Trang 1 ghi thành công
                        } else {
                            throw new RuntimeException("Lỗi ghi đĩa SQLite ở trang 2!"); // Trang 2 lỗi
                        }
                    }
                },
                inMemoryPrefs, logger
        );

        SyncResult res = pageFailManager.sync();
        assertFalse(res.isSuccess());

        // last_seq bắt buộc phải dừng ở 50L (cuối trang 1), không được nhảy lên 100L
        assertEquals(50L, inMemoryPrefs.getLastSeq());
    }

    // ---------------------------------------------------------------------------------
    // TEST 12: Bảng mã lỗi HTTP -> 403 (AUTH), 422 (VALIDATION - non-retry), 429/503 (SERVER - retryable)
    // ---------------------------------------------------------------------------------
    @Test
    public void test_HttpErrorCodes_MappingVerification() {
        int[] codes = {403, 422, 429, 503};
        SyncResult.ErrorType[] expectedTypes = {
                SyncResult.ErrorType.AUTH_ERROR,
                SyncResult.ErrorType.VALIDATION_ERROR,
                SyncResult.ErrorType.SERVER_ERROR,
                SyncResult.ErrorType.SERVER_ERROR
        };
        boolean[] expectedRetryable = {false, false, true, true};

        for (int i = 0; i < codes.length; i++) {
            final int code = codes[i];
            SyncManager mgr = new SyncManager(
                    new MockSyncApi() {
                        @Override
                        public SyncPushResponse push(SyncPushRequest request) throws Exception {
                            throw new SyncApiException(code, "HTTP " + code + " error");
                        }
                    },
                    new FakeSyncRepository() {{ addPendingChange(createSampleChange("c", "u", "s", "INSERT")); }},
                    inMemoryPrefs, logger
            );

            SyncResult res = mgr.sync();
            assertEquals("Code " + code + " sai errorType", expectedTypes[i], res.getErrorType());
            assertEquals("Code " + code + " sai retryable", expectedRetryable[i], res.isRetryable());
        }
    }

    // ---------------------------------------------------------------------------------
    // TEST 13: Pull phân trang chuẩn -> Lặp kéo đến khi has_more == false
    // ---------------------------------------------------------------------------------
    @Test
    public void test_PullPagination_ShouldLoopUntilHasMoreIsFalse() {
        mockApi.setScenario(MockSyncApi.Scenario.PULL_PAGINATION);

        SyncResult result = syncManager.sync();

        assertTrue(result.isSuccess());
        assertEquals(2, result.getPulledCount());
        assertEquals(2, mockApi.getPullCallCount());
        assertEquals(2L, fakeRepo.getLastSeq());
    }

    // ---------------------------------------------------------------------------------
    // TEST 14: Chống lặp vô hạn khi Pull (has_more = true nhưng new_seq không tăng)
    // ---------------------------------------------------------------------------------
    @Test
    public void test_PullInfiniteLoopGuard_ShouldThrowAndReturnErrorWhenSeqDoesNotAdvance() {
        SyncManager buggyServerManager = new SyncManager(
                new MockSyncApi() {
                    @Override
                    public SyncPullResponse pull(long sinceSeq, int limit) {
                        return new SyncPullResponse(sinceSeq, true, new ArrayList<>());
                    }
                },
                fakeRepo, inMemoryPrefs, logger
        );

        SyncResult result = buggyServerManager.sync();

        assertFalse(result.isSuccess());
        assertEquals(SyncResult.ErrorType.INTERNAL_ERROR, result.getErrorType());
        assertFalse(result.isRetryable());
    }

    // ---------------------------------------------------------------------------------
    // TEST 15: Server Wins -> Hủy các dòng PENDING cũ của cùng uuid trong outbox
    // ---------------------------------------------------------------------------------
    @Test
    public void test_ServerWins_ShouldCancelPendingOutboxItemForSameUuid() {
        fakeRepo.addPendingChange(createSampleChange("cid_local_1", "uuid_sv01", "students", "UPDATE"));
        assertEquals(1, fakeRepo.getPendingCount());

        JsonObject pulledPayload = new JsonObject();
        pulledPayload.addProperty("student_id", "SV_01");
        pulledPayload.addProperty("full_name", "Sinh Viên Tên Server");
        SyncChange serverChange = new SyncChange("cid_srv_1", "uuid_sv01", "students", "UPDATE", pulledPayload, System.currentTimeMillis());
        serverChange.setSeq(10L);

        fakeRepo.applyPulledChanges(Collections.singletonList(serverChange), 10L);

        // Dòng PENDING cục bộ phải bị CANCELLED
        assertEquals(0, fakeRepo.getPendingCount());
        assertEquals(FakeSyncRepository.OutboxStatus.CANCELLED, fakeRepo.getAllOutboxEntries().get(0).status);
    }

    // ---------------------------------------------------------------------------------
    // TEST 16: Idempotent Pull -> Kéo cùng dữ liệu 2 lần không làm trùng lặp SQLite
    // ---------------------------------------------------------------------------------
    @Test
    public void test_IdempotentPull_ShouldProduceSameDatabaseStateWhenAppliedTwice() {
        JsonObject payload = new JsonObject();
        payload.addProperty("id", "uuid_x");
        SyncChange change = new SyncChange("cid_1", "uuid_x", "students", "INSERT", payload, 1000L);

        List<SyncChange> list = Collections.singletonList(change);

        fakeRepo.applyPulledChanges(list, 1L);
        assertEquals(1, fakeRepo.getAppliedDatabase().size());

        fakeRepo.applyPulledChanges(list, 1L);
        assertEquals(1, fakeRepo.getAppliedDatabase().size());
    }

    // ---------------------------------------------------------------------------------
    // TEST 17: Crash nội bộ (RuntimeException) -> Luôn mở khóa lock trong finally VÀ isRetryable == false
    // ---------------------------------------------------------------------------------
    @Test
    public void test_InternalCrash_ShouldAlwaysReleaseLockAndNotRetry() {
        SyncManager crashingManager = new SyncManager(
                new MockSyncApi() {
                    @Override
                    public SyncPullResponse pull(long sinceSeq, int limit) {
                        throw new NullPointerException("NullPointer bất ngờ trong code!");
                    }
                },
                fakeRepo, inMemoryPrefs, logger
        );

        SyncResult result = crashingManager.sync();

        assertFalse(result.isSuccess());
        assertEquals(SyncResult.ErrorType.INTERNAL_ERROR, result.getErrorType());
        assertFalse("Bug code nội bộ không được retry vô hạn", result.isRetryable());
        assertFalse("Lock isSyncing bắt buộc phải về false", crashingManager.isSyncingNow());
    }

    // ---------------------------------------------------------------------------------
    // TEST 18: abortCurrentSync() gọi trước khi sync() -> Lần 1 dừng an toàn (SKIPPED_ABORTED), lần 2 chạy bình thường
    // ---------------------------------------------------------------------------------
    @Test
    public void test_AbortCurrentSync_ThenSyncAgain_ShouldAbortFirstThenWorkNormally() {
        // Đặt cờ abort trước khi sync bắt đầu (mô phỏng người dùng vừa bấm hủy hoặc đăng xuất trước đó)
        syncManager.abortCurrentSync();
        assertTrue(syncManager.isAborted());

        fakeRepo.addPendingChange(createSampleChange("cid_1", "uuid_1", "students", "INSERT"));
        mockApi.setScenario(MockSyncApi.Scenario.SUCCESS);

        // Lần 1: Nhận cờ abort ngay đầu chu trình -> Phải dừng ngay và trả về SKIPPED_ABORTED
        SyncResult firstResult = syncManager.sync();
        assertTrue(firstResult.isAborted());
        assertTrue(firstResult.isSkipped());
        assertEquals(SyncResult.ErrorType.SKIPPED_ABORTED, firstResult.getErrorType());
        assertFalse("Lock isSyncing phải được giải phóng về false", syncManager.isSyncingNow());
        assertEquals(1, fakeRepo.getPendingCount()); // Bản ghi chưa bị đẩy

        // Lần 2: Lệnh sync mới sau khi hủy -> Phải chạy thành công trọn vẹn
        SyncResult secondResult = syncManager.sync();
        assertTrue("Lần sync sau phải thành công bình thường", secondResult.isSuccess());
        assertFalse("Cờ isAborted phải là false", syncManager.isAborted());
        assertFalse("Lock isSyncing phải là false", syncManager.isSyncingNow());
        assertEquals(1, secondResult.getPushedCount());
        assertEquals(0, fakeRepo.getPendingCount());
    }

    // ---------------------------------------------------------------------------------
    // TEST 19: cancelAllSync() khi SyncManager chưa khởi tạo -> Tuyệt đối không crash
    // ---------------------------------------------------------------------------------
    @Test
    public void test_CancelAllSync_WhenSyncManagerNotInitialized_ShouldNotCrash() {
        SyncManager.resetInstanceForTesting();
        assertNull(SyncManager.getInstanceOrNull());

        // Gọi cancelAllSync khi instance đang null (mô phỏng logout lúc app mới mở)
        // Phải hoàn thành êm đẹp, không ném IllegalStateException hay NullPointerException
        SyncWorkScheduler.cancelAllSync(null);

        assertNull(SyncManager.getInstanceOrNull());
    }

    // ---------------------------------------------------------------------------------
    // TEST 20: Hủy giữa chừng khi đang push lô 1 -> Lô 2, 3 không được gửi, isSyncing về false
    // ---------------------------------------------------------------------------------
    @Test
    public void test_AbortMidPush_RemainingBatchesNeverSent_AndLockReleased() {
        // Tạo 250 bản ghi (Tương đương 3 lô: 100 + 100 + 50)
        for (int i = 1; i <= 250; i++) {
            fakeRepo.addPendingChange(createSampleChange("cid_" + i, "uuid_" + i, "students", "INSERT"));
        }
        assertEquals(250, fakeRepo.getPendingCount());

        final AtomicInteger pushCallCount = new AtomicInteger(0);
        final SyncManager[] managerRef = new SyncManager[1];

        SyncApi customApi = new SyncApi() {
            @Override
            public SyncPushResponse push(SyncPushRequest request) {
                int count = pushCallCount.incrementAndGet();
                List<String> ids = new ArrayList<>();
                for (SyncChange c : request.getChanges()) {
                    ids.add(c.getChangeId());
                }
                if (count == 1 && managerRef[0] != null) {
                    // Ngay khi lô 1 đẩy xong, kích hoạt hủy khẩn cấp (onStopped / cancelAllSync)
                    managerRef[0].abortCurrentSync();
                }
                return new SyncPushResponse(true, ids, Collections.emptyList(), null);
            }

            @Override
            public SyncPullResponse pull(long sinceSeq, int limit) {
                return new SyncPullResponse(sinceSeq, false, Collections.emptyList());
            }
        };

        SyncManager abortingSyncManager = new SyncManager(customApi, fakeRepo, inMemoryPrefs, logger);
        managerRef[0] = abortingSyncManager;

        // Chạy sync
        SyncResult result = abortingSyncManager.sync();

        // 1. Phải dừng ngay sau lô 1, các lô 2 và 3 tuyệt đối không được gửi
        assertEquals("Chỉ được gửi đúng 1 lô trước khi bị ngắt", 1, pushCallCount.get());

        // 2. Kết quả trả về phải là SKIPPED_ABORTED (không trả về success giả hay lỗi giả)
        assertTrue(result.isAborted());
        assertTrue(result.isSkipped());
        assertEquals(SyncResult.ErrorType.SKIPPED_ABORTED, result.getErrorType());

        // 3. Lock isSyncing bắt buộc phải về false
        assertFalse("Lock isSyncing bắt buộc phải giải phóng về false", abortingSyncManager.isSyncingNow());

        // 4. Lô 1 (100 item) đã sync, còn lại 150 item vẫn còn nguyên trong outbox
        assertEquals(150, fakeRepo.getPendingCount());

        // 5. Thử sync lần thứ hai: các lô còn lại (150 item) phải được tiếp tục đẩy bình thường
        SyncResult secondResult = abortingSyncManager.sync();
        assertTrue(secondResult.isSuccess());
        assertEquals(0, fakeRepo.getPendingCount());
        assertEquals(3, pushCallCount.get()); // Lô 2 và lô 3 được gửi thành công
    }
}
