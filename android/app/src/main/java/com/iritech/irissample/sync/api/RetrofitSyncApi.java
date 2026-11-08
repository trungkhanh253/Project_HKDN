package com.iritech.irissample.sync.api;

import com.google.gson.JsonSyntaxException;
import com.iritech.irissample.sync.model.SyncPullResponse;
import com.iritech.irissample.sync.model.SyncPushRequest;
import com.iritech.irissample.sync.model.SyncPushResponse;
import retrofit2.Response;

/**
 * Triển khai SyncApi thực tế sử dụng Retrofit (dành cho môi trường chạy thật)
 * Bọc các lỗi JsonSyntaxException và mã HTTP thành SyncApiException thống nhất.
 */
public class RetrofitSyncApi implements SyncApi {

    private final SyncApiService service;

    public RetrofitSyncApi(SyncApiService service) {
        this.service = service;
    }

    @Override
    public SyncPushResponse push(SyncPushRequest request) throws Exception {
        try {
            Response<SyncPushResponse> response = service.pushChanges(request).execute();

            if (response.isSuccessful() && response.body() != null) {
                return response.body();
            }

            int code = response.code();
            String errorBody = response.errorBody() != null ? response.errorBody().string() : "Empty error body";
            throw new SyncApiException(code, "Push HTTP " + code + ": " + errorBody);

        } catch (JsonSyntaxException e) {
            throw new SyncApiException(500, "Push failed: Malformed JSON syntax from server: " + e.getMessage());
        }
    }

    @Override
    public SyncPullResponse pull(long sinceSeq, int limit) throws Exception {
        try {
            Response<SyncPullResponse> response = service.pullChanges(sinceSeq, limit).execute();

            if (response.isSuccessful() && response.body() != null) {
                return response.body();
            }

            int code = response.code();
            String errorBody = response.errorBody() != null ? response.errorBody().string() : "Empty error body";
            throw new SyncApiException(code, "Pull HTTP " + code + ": " + errorBody);

        } catch (JsonSyntaxException e) {
            throw new SyncApiException(500, "Pull failed: Malformed JSON syntax from server: " + e.getMessage());
        }
    }
}
