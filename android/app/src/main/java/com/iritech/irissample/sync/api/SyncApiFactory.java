
package com.iritech.irissample.sync.api;

import android.content.Context;

import com.iritech.irissample.auth.TokenAuthenticator;
import com.iritech.irissample.sync.data.ISyncPrefs;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

import okhttp3.ConnectionPool;
import okhttp3.HttpUrl;
import okhttp3.Interceptor;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.logging.HttpLoggingInterceptor;

import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public class SyncApiFactory {

    private static SyncApiService cachedService;
    private static String cachedBaseUrl;
    private static String cachedToken;
    private static OkHttpClient cachedClient;

    // NEW: Context để khởi tạo TokenAuthenticator
    private static Context appContext;

    private static final ConnectionPool SHARED_CONNECTION_POOL =
            new ConnectionPool(5, 5, TimeUnit.MINUTES);

    public static String normalizeAndValidateBaseUrl(String rawUrl)
            throws IllegalArgumentException {

        if (rawUrl == null || rawUrl.trim().isEmpty()) {
            return "http://127.0.0.1:5000/";
        }

        String url = rawUrl.trim();

        if (!url.startsWith("http://")
                && !url.startsWith("https://")) {
            url = "http://" + url;
        }

        if (!url.endsWith("/")) {
            url += "/";
        }

        HttpUrl parsed = HttpUrl.parse(url);

        if (parsed == null) {
            throw new IllegalArgumentException(
                    "Địa chỉ máy chủ không hợp lệ: " + rawUrl
            );
        }

        return url;
    }

    public static synchronized SyncApiService createService(
            final ISyncPrefs prefs
    ) {

        String baseUrl =
                normalizeAndValidateBaseUrl(prefs.getServerUrl());

        String token = prefs.getAuthToken() != null
                ? prefs.getAuthToken().trim()
                : "";

        // Giữ nguyên cơ chế cache theo URL và Token
        if (cachedService != null
                && baseUrl.equals(cachedBaseUrl)
                && token.equals(cachedToken)) {
            return cachedService;
        }

        // FIX: Tạo lại client nếu URL thay đổi
        if (cachedClient == null
                || !baseUrl.equals(cachedBaseUrl)) {

            HttpLoggingInterceptor logging =
                    new HttpLoggingInterceptor();

            // FIX: Tránh ghi nội dung đồng bộ nhạy cảm
            logging.setLevel(
                    HttpLoggingInterceptor.Level.NONE
            );

            logging.redactHeader("Authorization");

            OkHttpClient.Builder clientBuilder =
                    new OkHttpClient.Builder()
                            .connectionPool(
                                    SHARED_CONNECTION_POOL
                            )
                            .connectTimeout(
                                    15, TimeUnit.SECONDS
                            )
                            .readTimeout(
                                    30, TimeUnit.SECONDS
                            )
                            .writeTimeout(
                                    30, TimeUnit.SECONDS
                            )
                            .addInterceptor(new Interceptor() {
                                @Override
                                public Response intercept(Chain chain)
                                        throws IOException {

                                    Request original =
                                            chain.request();

                                    Request.Builder builder =
                                            original.newBuilder();

                                    // Giữ nguyên: đọc JWT động từ prefs
                                    String currentToken =
                                            prefs.getAuthToken();

                                    if (currentToken != null
                                            && !currentToken.trim().isEmpty()) {

                                        builder.header(
                                                "Authorization",
                                                "Bearer " + currentToken.trim()
                                        );
                                    }

                                    builder.header(
                                            "Accept",
                                            "application/json"
                                    );

                                    builder.header(
                                            "Content-Type",
                                            "application/json"
                                    );

                                    return chain.proceed(
                                            builder.build()
                                    );
                                }
                            });

            // NEW: Tự động refresh JWT khi HTTP 401
            if (appContext != null) {
                clientBuilder.authenticator(
                        new TokenAuthenticator(
                                appContext,
                                baseUrl
                        )
                );
            }

            cachedClient = clientBuilder
                    .addInterceptor(logging)
                    .build();
        }

        Retrofit retrofit = new Retrofit.Builder()
                .baseUrl(baseUrl)
                .client(cachedClient)
                .addConverterFactory(
                        GsonConverterFactory.create()
                )
                .build();

        cachedService =
                retrofit.create(SyncApiService.class);

        cachedBaseUrl = baseUrl;
        cachedToken = token;

        return cachedService;
    }

    public static synchronized void clearCache() {

        cachedService = null;
        cachedBaseUrl = null;
        cachedToken = null;
        cachedClient = null;
    }

    // NEW: Khởi tạo Context một lần
    public static synchronized void initialize(Context context) {

        if (context == null) {
            throw new IllegalArgumentException(
                    "Context không được null"
            );
        }

        appContext = context.getApplicationContext();

        clearCache();
    }
}
