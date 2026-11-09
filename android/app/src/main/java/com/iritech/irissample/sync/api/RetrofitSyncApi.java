package com.iritech.irissample.sync.api;

import com.google.gson.JsonSyntaxException;
import com.iritech.irissample.sync.data.ISyncPrefs;
import com.iritech.irissample.sync.model.SyncPullResponse;
import com.iritech.irissample.sync.model.SyncPushRequest;
import com.iritech.irissample.sync.model.SyncPushResponse;
import retrofit2.Response;

/**
 * Triển khai SyncApi thực tế sử dụng Retrofit (dành cho môi trường chạy thật)
 * Bọc các lỗi JsonSyntaxException và mã HTTP thành SyncApiException thống nhất.
 * Hỗ trợ nhận ISyncPrefs để tự động cập nhật Base URL / Token khi người dùng đổi trong Cài đặt.
 */
public class RetrofitSyncApi implements SyncApi {

    private final ISyncPrefs prefs;
    private SyncApiService service;

    public RetrofitSyncApi(SyncApiService service) {
        this.service = service;
        this.prefs = null;
    }

    public RetrofitSyncApi(ISyncPrefs prefs) {
        this.prefs = prefs;
        this.service = null;
    }

    private SyncApiService getService() {
        if (prefs != null) {
            return SyncApiFactory.createService(prefs);
        }
        return service;
    }

    @Override
    public SyncPushResponse push(SyncPushRequest request) throws Exception {
        try {
            Response<SyncPushResponse> response = getService().pushChanges(request).execute();

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
            Response<SyncPullResponse> response = getService().pullChanges(sinceSeq, limit).execute();

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
