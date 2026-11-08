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
 * Ném cùng loại Exception với RetrofitSyncApi (SyncApiException cho HTTP và IOException cho Mạng)
 */
public class MockSyncApi implements SyncApi {

    public enum Scenario {
        SUCCESS,                 // Push & Pull đều thành công
        NETWORK_ERROR,           // Lỗi mất mạng / Timeout (ném IOException)
        HTTP_401_UNAUTHORIZED,   // Hết hạn token / Chưa đăng nhập (SyncApiException 401)
        HTTP_500_SERVER_ERROR,   // Server lỗi nội bộ (SyncApiException 500)
        PUSH_PARTIAL_SUCCESS,    // Push một phần (nửa thành công, nửa thất bại)
        PUSH_ALL_REJECTED,       // Toàn bộ bản ghi bị server từ chối
        PULL_EMPTY,              // Pull về danh sách rỗng
        PULL_PAGINATION,         // Lần 1 trả has_more = true, lần 2 trả has_more = false
        PULL_ERROR               // Push ok nhưng Pull bị lỗi 500
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
                throw new SyncApiException(401, "Token expired or unauthorized");

            case HTTP_500_SERVER_ERROR:
                throw new SyncApiException(500, "Internal Server Error in database");

            case PUSH_ALL_REJECTED:
                List<String> allFailed = new ArrayList<>();
                if (request.getChanges() != null) {
                    for (SyncChange c : request.getChanges()) {
                        allFailed.add(c.getChangeId() != null ? c.getChangeId() : c.getUuid());
                    }
                }
                return new SyncPushResponse(false, new ArrayList<String>(), allFailed, "All items rejected");

            case PUSH_PARTIAL_SUCCESS:
                List<String> synced = new ArrayList<>();
                List<String> failed = new ArrayList<>();
                if (request.getChanges() != null) {
                    for (int i = 0; i < request.getChanges().size(); i++) {
                        SyncChange c = request.getChanges().get(i);
                        String id = c.getChangeId() != null ? c.getChangeId() : c.getUuid();
                        if (i % 2 == 0) {
                            synced.add(id);
                        } else {
                            failed.add(id);
                        }
                    }
                }
                return new SyncPushResponse(true, synced, failed, "Partial push: some items failed validation");

            case SUCCESS:
            case PULL_EMPTY:
            case PULL_PAGINATION:
            case PULL_ERROR:
            default:
                List<String> allSynced = new ArrayList<>();
                if (request.getChanges() != null) {
                    for (SyncChange c : request.getChanges()) {
                        allSynced.add(c.getChangeId() != null ? c.getChangeId() : c.getUuid());
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
            throw new SyncApiException(401, "Token expired during pull");
        }
        if (scenario == Scenario.PULL_ERROR || scenario == Scenario.HTTP_500_SERVER_ERROR) {
            throw new SyncApiException(500, "Server failed to fetch seq changes");
        }
        if (scenario == Scenario.PULL_EMPTY) {
            return new SyncPullResponse(sinceSeq, false, new ArrayList<SyncChange>());
        }

        if (scenario == Scenario.PULL_PAGINATION) {
            // Lần 1: trả has_more = true, new_seq = sinceSeq + 1
            if (pullCallCount == 1) {
                List<SyncChange> page1 = new ArrayList<>();
                JsonObject p1 = new JsonObject();
                p1.addProperty("student_id", "SV_PAGE1");
                SyncChange c1 = new SyncChange("cid_pull_1", "uuid_p1", "students", "INSERT", p1, System.currentTimeMillis());
                c1.setSeq(sinceSeq + 1);
                page1.add(c1);
                return new SyncPullResponse(sinceSeq + 1, true, page1);
            } else {
                // Lần 2: trả has_more = false, new_seq = sinceSeq + 1
                List<SyncChange> page2 = new ArrayList<>();
                JsonObject p2 = new JsonObject();
                p2.addProperty("student_id", "SV_PAGE2");
                SyncChange c2 = new SyncChange("cid_pull_2", "uuid_p2", "students", "INSERT", p2, System.currentTimeMillis());
                c2.setSeq(sinceSeq + 1);
                page2.add(c2);
                return new SyncPullResponse(sinceSeq + 1, false, page2);
            }
        }

        // Mặc định trả về 1 bản ghi
        List<SyncChange> changes = new ArrayList<>();
        JsonObject studentPayload = new JsonObject();
        studentPayload.addProperty("student_id", "SV_PULLED_01");
        studentPayload.addProperty("full_name", "Sinh Viên Kéo Từ Server");

        SyncChange change1 = new SyncChange("cid_pull_1", "pulled-uuid-001", "students", "INSERT", studentPayload, System.currentTimeMillis());
        change1.setSeq(sinceSeq + 1);
        changes.add(change1);

        long nextSeq = Math.max(mockServerNewSeq, sinceSeq + 1);
        return new SyncPullResponse(nextSeq, false, changes);
    }
}
