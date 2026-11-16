package com.iritech.irissample.sync.api;

import com.iritech.irissample.sync.model.SyncPullResponse;
import com.iritech.irissample.sync.model.SyncPushRequest;
import com.iritech.irissample.sync.model.SyncPushResponse;

/**
 * Interface giao tiếp mạng của Sync Engine
 * SyncManager chỉ tương tác với Interface này, giúp dễ dàng đổi giữa MockSyncApi và RetrofitSyncApi.
 */
public interface SyncApi {

    /**
     * Đẩy danh sách thay đổi từ local lên Server (POST /api/v1/sync/push)
     * @param request Gói tin chứa mảng changes
     * @return Phản hồi từ server với danh sách synced_uuids và failed_uuids
     * @throws Exception nếu có lỗi mạng, lỗi HTTP 401, 5xx, v.v.
     */
    SyncPushResponse push(SyncPushRequest request) throws Exception;

    /**
     * Kéo danh sách thay đổi mới từ Server về SQLite (GET /api/v1/sync/pull)
     * @param sinceSeq Con trỏ sequence lấy từ lần sync trước
     * @param limit Số lượng bản ghi tối đa mỗi lần kéo (ví dụ 100)
     * @return Phản hồi chứa mảng changes và new_seq
     * @throws Exception nếu có lỗi mạng hoặc lỗi server
     */
    SyncPullResponse pull(long sinceSeq, int limit) throws Exception;
}
