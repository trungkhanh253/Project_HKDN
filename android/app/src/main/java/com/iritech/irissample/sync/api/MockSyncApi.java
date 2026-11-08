package com.iritech.irissample.sync.api;

import com.google.gson.JsonObject;
import com.iritech.irissample.sync.model.SyncChange;
import com.iritech.irissample.sync.model.SyncPullResponse;
import com.iritech.irissample.sync.model.SyncPushRequest;
import com.iritech.irissample.sync.model.SyncPushResponse;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * Lớp Mock API giả lập Server phục vụ Unit Test và phát triển độc lập
 * Cho phép thiết lập kịch bản (Scenario) để kiểm thử toàn diện các case lỗi.
 */
public class MockSyncApi implements SyncApi {

    public enum Scenario {
        SUCCESS,                 // Push & Pull đều thành công mỹ mãn
        NETWORK_ERROR,           // Lỗi mất mạng / Timeout (ném IOException)
        HTTP_401_UNAUTHORIZED,   // Hết hạn token / Sai thông tin đăng nhập
        HTTP_500_SERVER_ERROR,   // Server nội bộ 500
        PUSH_PARTIAL_SUCCESS,    // Push một phần (nửa thành công, nửa thất bại)
        PULL_EMPTY,              // Pull về danh sách rỗng (không có thay đổi mới)
        PULL_ERROR               // Push thì thành công nhưng Pull bị lỗi
    }

    public static class ApiException extends Exception {
        private final int statusCode;

        public ApiException(int statusCode, String message) {
            super(message);
            this.statusCode = statusCode;
        }

        public int getStatusCode() {
            return statusCode;
        }
    }

    private Scenario scenario = Scenario.SUCCESS;
    private SyncPushRequest lastPushRequest;
    private long lastPullSinceSeq = -1;
    private int pushCallCount = 0;
    private int pullCallCount = 0;
    private long mockServerNewSeq = 100L;

    public void setScenario(Scenario scenario) {
        this.scenario = scenario;
    }

    public void setMockServerNewSeq(long newSeq) {
        this.mockServerNewSeq = newSeq;
    }

    public SyncPushRequest getLastPushRequest() {
        return lastPushRequest;
    }

    public long getLastPullSinceSeq() {
        return lastPullSinceSeq;
    }

    public int getPushCallCount() {
        return pushCallCount;
    }

    public int getPullCallCount() {
        return pullCallCount;
    }

    @Override
    public SyncPushResponse push(SyncPushRequest request) throws Exception {
        this.pushCallCount++;
        this.lastPushRequest = request;

        switch (scenario) {
            case NETWORK_ERROR:
                throw new IOException("Failed to connect to mock server (Network timeout)");

            case HTTP_401_UNAUTHORIZED:
                throw new ApiException(401, "Token expired or unauthorized");

            case HTTP_500_SERVER_ERROR:
                throw new ApiException(500, "Internal Server Error in database");

            case PUSH_PARTIAL_SUCCESS:
                List<String> synced = new ArrayList<>();
                List<String> failed = new ArrayList<>();
                if (request.getChanges() != null) {
                    for (int i = 0; i < request.getChanges().size(); i++) {
                        String uuid = request.getChanges().get(i).getUuid();
                        if (i % 2 == 0) {
                            synced.add(uuid); // Chẵn thì thành công
                        } else {
                            failed.add(uuid); // Lẻ thì thất bại
                        }
                    }
                }
                return new SyncPushResponse(true, synced, failed, "Partial push: some items failed validation");

            case SUCCESS:
            case PULL_EMPTY:
            case PULL_ERROR:
            default:
                List<String> allSynced = new ArrayList<>();
                if (request.getChanges() != null) {
                    for (SyncChange c : request.getChanges()) {
                        allSynced.add(c.getUuid());
                    }
                }
                return new SyncPushResponse(true, allSynced, new ArrayList<String>(), null);
        }
    }

    @Override
    public SyncPullResponse pull(long sinceSeq, int limit) throws Exception {
        this.pullCallCount++;
        this.lastPullSinceSeq = sinceSeq;

        if (scenario == Scenario.NETWORK_ERROR) {
            throw new IOException("Failed to connect to mock server while pulling");
        }
        if (scenario == Scenario.HTTP_401_UNAUTHORIZED) {
            throw new ApiException(401, "Token expired during pull");
        }
        if (scenario == Scenario.PULL_ERROR || scenario == Scenario.HTTP_500_SERVER_ERROR) {
            throw new ApiException(500, "Server failed to fetch seq changes");
        }

        if (scenario == Scenario.PULL_EMPTY) {
            return new SyncPullResponse(sinceSeq, false, new ArrayList<SyncChange>());
        }

        // Kịch bản mặc định có dữ liệu trả về
        List<SyncChange> changes = new ArrayList<>();
        JsonObject studentPayload = new JsonObject();
        studentPayload.addProperty("student_id", "SV_PULLED_01");
        studentPayload.addProperty("full_name", "Sinh Viên Kéo Từ Server");

        SyncChange change1 = new SyncChange("pulled-uuid-001", "students", "INSERT", studentPayload, System.currentTimeMillis());
        change1.setSeq(sinceSeq + 1);
        changes.add(change1);

        long nextSeq = Math.max(mockServerNewSeq, sinceSeq + 1);
        return new SyncPullResponse(nextSeq, false, changes);
    }
}
