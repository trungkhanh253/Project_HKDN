
package com.iritech.irissample.auth;

import android.content.Context;

import androidx.annotation.Nullable;

import com.google.gson.Gson;
import com.iritech.irissample.sync.data.AndroidSyncPrefs;

import java.io.IOException;

import okhttp3.Authenticator;
import okhttp3.Credentials;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.Route;
import android.util.Log;

public class TokenAuthenticator implements Authenticator {

    private static final MediaType JSON =
            MediaType.parse("application/json; charset=utf-8");

    private final AndroidSyncPrefs prefs;
    private final OkHttpClient refreshClient;
    private final String refreshUrl;
    private final Gson gson = new Gson();

    public TokenAuthenticator(
            Context context,
            String serverUrl
    ) {
        prefs = new AndroidSyncPrefs(context.getApplicationContext());

        refreshClient = new OkHttpClient.Builder()
                .build();

        refreshUrl = serverUrl + "api/v1/auth/refresh";
    }

    @Nullable
    @Override
    public Request authenticate(
            Route route,
            Response response
    ) throws IOException {
        Log.d("REFRESH_TEST", "Nhận HTTP 401, bắt đầu xử lý Refresh Token");

        // Không refresh khi chính endpoint refresh bị 401
        String path = response.request().url().encodedPath();

        if (path.endsWith("/auth/login")
                || path.endsWith("/auth/refresh")) {
            return null;
        }
        // Chỉ retry một lầna
        if (responseCount(response) >= 2) {
            return null;
        }

        synchronized (this) {

            String oldToken = prefs.getAuthToken();
            String requestAuthorization =
                    response.request().header("Authorization");

            // Nếu request dùng token cũ nhưng token đã được
            // một request khác refresh, chỉ cần dùng token mới
            if (oldToken != null
                    && !oldToken.isEmpty()
                    && requestAuthorization != null
                    && !requestAuthorization.equals("Bearer " + oldToken)) {

                return response.request()
                        .newBuilder()
                        .header("Authorization", "Bearer " + oldToken)
                        .build();
            }

            String refreshToken = prefs.getRefreshToken();

            if (refreshToken == null || refreshToken.isEmpty()) {
                return null;
            }

            RefreshTokenRequest refreshRequest =
                    new RefreshTokenRequest(refreshToken);

            RequestBody body = RequestBody.create(
                    JSON,
                    gson.toJson(refreshRequest)
            );

            Request request = new Request.Builder()
                    .url(refreshUrl)
                    .post(body)
                    .build();
            Log.d("REFRESH_TEST", "Đang gọi POST /api/v1/auth/refresh");
            try (Response refreshResponse =
                         refreshClient.newCall(request).execute()) {

                if (!refreshResponse.isSuccessful()
                        || refreshResponse.body() == null) {

                    if (refreshResponse.code() == 401) {
                        prefs.clearAuthSession();
                    }

                    return null;
                }

                RefreshTokenResponse tokenResponse =
                        gson.fromJson(
                                refreshResponse.body().charStream(),
                                RefreshTokenResponse.class
                        );

                if (tokenResponse == null
                        || tokenResponse.accessToken == null
                        || tokenResponse.accessToken.isEmpty()) {
                    return null;
                }

                prefs.setAuthToken(tokenResponse.accessToken);
                if (tokenResponse.refreshToken != null
                        && !tokenResponse.refreshToken.isEmpty()) {
                    prefs.setRefreshToken(tokenResponse.refreshToken);
                }

                Log.d("REFRESH_TEST", "Refresh Token thành công, đã lưu Access Token mới");

                return response.request()
                        .newBuilder()
                        .header(
                                "Authorization",
                                "Bearer " + tokenResponse.accessToken
                        )
                        .build();
            }
        }
    }

    private int responseCount(Response response) {
        int count = 1;

        while ((response = response.priorResponse()) != null) {
            count++;
        }

        return count;
    }
}
