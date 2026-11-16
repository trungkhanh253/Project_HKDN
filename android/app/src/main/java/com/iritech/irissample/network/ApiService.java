package com.iritech.irissample.network;

import com.google.gson.JsonObject;

import retrofit2.Call;
import retrofit2.http.GET;

public interface  ApiService {
    @GET("health")
    Call<JsonObject> checkHealth();
}
