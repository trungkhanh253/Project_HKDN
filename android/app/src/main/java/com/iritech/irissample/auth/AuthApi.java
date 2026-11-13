
package com.iritech.irissample.auth;

import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.Header;
import retrofit2.http.POST;

public interface AuthApi {

    @POST("api/v1/auth/login")
    Call<LoginResponse> login(
            @Body LoginRequest request
    );

    @GET("api/v1/auth/me")
    Call<MeResponse> getCurrentUser(
            @Header("Authorization") String token
    );

    @POST("api/v1/auth/refresh")
    Call<RefreshTokenResponse> refreshToken(
            @Body RefreshTokenRequest request
    );
}
