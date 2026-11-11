package com.iritech.irissample.sync.api;

import com.iritech.irissample.sync.model.SyncPullResponse;
import com.iritech.irissample.sync.model.SyncPushRequest;
import com.iritech.irissample.sync.model.SyncPushResponse;
import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.POST;
import retrofit2.http.Query;

/**
 * Interface Retrofit định nghĩa các endpoints đồng bộ của Backend
 */
public interface SyncApiService {

    @POST("api/v1/sync/push")
    Call<SyncPushResponse> pushChanges(@Body SyncPushRequest request);

    @GET("api/v1/sync/pull")
    Call<SyncPullResponse> pullChanges(
            @Query("since_seq") long sinceSeq,
            @Query("limit") int limit
    );
}
