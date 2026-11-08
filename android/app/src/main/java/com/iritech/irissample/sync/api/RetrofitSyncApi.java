package com.iritech.irissample.sync.api;

import com.iritech.irissample.sync.model.SyncPullResponse;
import com.iritech.irissample.sync.model.SyncPushRequest;
import com.iritech.irissample.sync.model.SyncPushResponse;
import java.io.IOException;
import retrofit2.Response;

/**
 * Triển khai SyncApi thực tế sử dụng Retrofit (dành cho môi trường chạy thật)
 * Thực thi các lệnh mạng dạng đồng bộ (Blocking .execute()) bên trong luồng nền của Worker.
 */
public class RetrofitSyncApi implements SyncApi {

    private final SyncApiService service;

    public RetrofitSyncApi(SyncApiService service) {
        this.service = service;
    }

    @Override
    public SyncPushResponse push(SyncPushRequest request) throws Exception {
        Response<SyncPushResponse> response = service.pushChanges(request).execute();

        if (response.isSuccessful() && response.body() != null) {
            return response.body();
        }

        int code = response.code();
        String errorBody = response.errorBody() != null ? response.errorBody().string() : "Unknown error";
        throw new MockSyncApi.ApiException(code, "Push failed with HTTP " + code + ": " + errorBody);
    }

    @Override
    public SyncPullResponse pull(long sinceSeq, int limit) throws Exception {
        Response<SyncPullResponse> response = service.pullChanges(sinceSeq, limit).execute();

        if (response.isSuccessful() && response.body() != null) {
            return response.body();
        }

        int code = response.code();
        String errorBody = response.errorBody() != null ? response.errorBody().string() : "Unknown error";
        throw new MockSyncApi.ApiException(code, "Pull failed with HTTP " + code + ": " + errorBody);
    }
}
