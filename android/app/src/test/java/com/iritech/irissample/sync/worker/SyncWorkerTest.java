package com.iritech.irissample.sync.worker;

import static org.junit.Assert.assertEquals;

import com.iritech.irissample.sync.model.SyncResult;
import org.junit.Test;

/**
 * Unit Test thuần túy trên JVM kiểm chứng logic chuyển đổi SyncResult -> WorkManager Outcome của SyncWorker.
 * Không phụ thuộc Android Runtime hay work-testing.
 */
public class SyncWorkerTest {

    @Test
    public void testDecide_Success_ShouldReturnSuccess() {
        SyncResult result = SyncResult.success(10, 5, 0);
        assertEquals(SyncWorker.Outcome.SUCCESS, SyncWorker.decideOutcome(result, 0));
        assertEquals(SyncWorker.Outcome.SUCCESS, SyncWorker.decideOutcome(result, 3));
    }

    @Test
    public void testDecide_Skipped_ShouldReturnSuccess() {
        // SKIPPED_STANDALONE
        SyncResult r1 = SyncResult.skippedStandalone();
        assertEquals(SyncWorker.Outcome.SUCCESS, SyncWorker.decideOutcome(r1, 0));

        // SKIPPED_NO_CONFIG
        SyncResult r2 = SyncResult.skippedNoConfig();
        assertEquals(SyncWorker.Outcome.SUCCESS, SyncWorker.decideOutcome(r2, 0));

        // SKIPPED_CONCURRENT
        SyncResult r3 = SyncResult.skippedConcurrent();
        assertEquals(SyncWorker.Outcome.SUCCESS, SyncWorker.decideOutcome(r3, 0));
    }

    @Test
    public void testDecide_NullResult_ShouldReturnSuccess() {
        assertEquals(SyncWorker.Outcome.SUCCESS, SyncWorker.decideOutcome(null, 0));
    }

    @Test
    public void testDecide_NetworkError_ShouldRetryUnderMaxLimit() {
        SyncResult result = SyncResult.error(SyncResult.ErrorType.NETWORK_ERROR, "Connection timed out");
        // Attempt 0, 1, 4 < MAX_WORKER_RETRIES (5) -> RETRY
        assertEquals(SyncWorker.Outcome.RETRY, SyncWorker.decideOutcome(result, 0));
        assertEquals(SyncWorker.Outcome.RETRY, SyncWorker.decideOutcome(result, 1));
        assertEquals(SyncWorker.Outcome.RETRY, SyncWorker.decideOutcome(result, 4));
    }

    @Test
    public void testDecide_NetworkError_ShouldFailWhenMaxLimitReached() {
        SyncResult result = SyncResult.error(SyncResult.ErrorType.NETWORK_ERROR, "Connection timed out");
        // Attempt >= 5 -> FAILURE
        assertEquals(SyncWorker.Outcome.FAILURE, SyncWorker.decideOutcome(result, 5));
        assertEquals(SyncWorker.Outcome.FAILURE, SyncWorker.decideOutcome(result, 6));
    }

    @Test
    public void testDecide_ServerError_ShouldRetryUnderLimitAndFailAtLimit() {
        SyncResult result = SyncResult.error(SyncResult.ErrorType.SERVER_ERROR, "500 Internal Server Error");
        assertEquals(SyncWorker.Outcome.RETRY, SyncWorker.decideOutcome(result, 0));
        assertEquals(SyncWorker.Outcome.RETRY, SyncWorker.decideOutcome(result, 2));
        assertEquals(SyncWorker.Outcome.FAILURE, SyncWorker.decideOutcome(result, 5));
    }

    @Test
    public void testDecide_AuthError_ShouldFailImmediatelyWithoutRetry() {
        SyncResult result = SyncResult.error(SyncResult.ErrorType.AUTH_ERROR, "401 Token expired");
        // Lỗi xác thực không được retry vô ích, trả về FAILURE ngay lần 0
        assertEquals(SyncWorker.Outcome.FAILURE, SyncWorker.decideOutcome(result, 0));
    }

    @Test
    public void testDecide_ValidationError_ShouldFailImmediatelyWithoutRetry() {
        SyncResult result = SyncResult.error(SyncResult.ErrorType.VALIDATION_ERROR, "422 Invalid payload format");
        // Lỗi 422 cấu trúc dữ liệu không được retry
        assertEquals(SyncWorker.Outcome.FAILURE, SyncWorker.decideOutcome(result, 0));
    }

    @Test
    public void testDecide_InternalError_ShouldFailImmediately() {
        SyncResult result = SyncResult.error(SyncResult.ErrorType.INTERNAL_ERROR, "NullPointerException during DB access");
        assertEquals(SyncWorker.Outcome.FAILURE, SyncWorker.decideOutcome(result, 0));
    }
}
