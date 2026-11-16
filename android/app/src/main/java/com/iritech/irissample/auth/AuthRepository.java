
package com.iritech.irissample.auth;

import android.content.Context;

import com.iritech.irissample.sync.data.AndroidSyncPrefs;

import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public class AuthRepository {

    private final AuthApi authApi;
    private final Context context;

    public AuthRepository(Context context) {

        this.context = context.getApplicationContext();

        AndroidSyncPrefs prefs = new AndroidSyncPrefs(context);

        String serverUrl = prefs.getServerUrl();

        if (serverUrl == null || serverUrl.trim().isEmpty()) {
            throw new IllegalStateException(
                    "Chưa cấu hình Server URL"
            );
        }

        serverUrl = serverUrl.trim();

        if (!serverUrl.endsWith("/")) {
            serverUrl += "/";
        }

        OkHttpClient client = new OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(20, TimeUnit.SECONDS)
                .writeTimeout(20, TimeUnit.SECONDS)
                .authenticator(
                        new TokenAuthenticator(this.context, serverUrl)
                )
                .build();

        Retrofit retrofit = new Retrofit.Builder()
                .baseUrl(serverUrl)
                .client(client)
                .addConverterFactory(GsonConverterFactory.create())
                .build();

        authApi = retrofit.create(AuthApi.class);
    }

    public void login(
            String email,
            String password,
            LoginCallback callback
    ) {

        LoginRequest request = new LoginRequest(email, password);

        authApi.login(request).enqueue(new Callback<LoginResponse>() {

            @Override
            public void onResponse(
                    Call<LoginResponse> call,
                    Response<LoginResponse> response
            ) {

                LoginResponse body = response.body();

                if (response.isSuccessful()
                        && body != null
                        && body.accessToken != null
                        && !body.accessToken.isEmpty()
                        && body.admin != null) {

                    callback.onSuccess(body);

                } else if (response.code() == 401) {
                    callback.onError("Email hoặc mật khẩu không đúng");

                } else {
                    callback.onError(
                            "Đăng nhập thất bại. HTTP " + response.code()
                    );
                }
            }

            @Override
            public void onFailure(
                    Call<LoginResponse> call,
                    Throwable t
            ) {
                callback.onError(
                        "Không thể kết nối Server: " + t.getMessage()
                );
            }
        });
    }

    public interface LoginCallback {
        void onSuccess(LoginResponse response);
        void onError(String message);
    }


    public void getCurrentUser(MeCallback callback) {

        AndroidSyncPrefs prefs =
                new AndroidSyncPrefs(context);

        String token = prefs.getAuthToken();

        if (token == null || token.trim().isEmpty()) {
            callback.onError("Chưa có JWT. Vui lòng đăng nhập lại.");
            return;
        }

        authApi.getCurrentUser("Bearer " + token)
                .enqueue(new Callback<MeResponse>() {

                    @Override
                    public void onResponse(
                            Call<MeResponse> call,
                            Response<MeResponse> response
                    ) {
                        if (response.isSuccessful()
                                && response.body() != null
                                && response.body().admin != null) {

                            callback.onSuccess(response.body());

                        } else if (response.code() == 401) {
                            callback.onError("JWT hết hạn hoặc không hợp lệ.");

                        } else {
                            callback.onError(
                                    "Không thể lấy thông tin Admin. HTTP "
                                            + response.code()
                            );
                        }
                    }

                    @Override
                    public void onFailure(
                            Call<MeResponse> call,
                            Throwable t
                    ) {
                        callback.onError(
                                "Lỗi kết nối Flask: " + t.getMessage()
                        );
                    }
                });
    }

    public interface MeCallback {
        void onSuccess(MeResponse response);
        void onError(String message);
    }

}
