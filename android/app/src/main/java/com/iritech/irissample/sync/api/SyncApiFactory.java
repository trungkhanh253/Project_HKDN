package com.iritech.irissample.sync.api;

import com.iritech.irissample.sync.data.ISyncPrefs;
import java.io.IOException;
import java.util.concurrent.TimeUnit;
import okhttp3.HttpUrl;
import okhttp3.Interceptor;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

/**
 * Factory khởi tạo Retrofit API Service với Dynamic Base URL và Token từ ISyncPrefs
 * Có cơ chế Cache Retrofit & OkHttpClient để tái sử dụng, tránh tạo lại tốn tài nguyên.
 */
public class SyncApiFactory {

    private static SyncApiService cachedService;
    private static String cachedBaseUrl;
    private static String cachedToken;

    public static String normalizeAndValidateBaseUrl(String rawUrl) throws IllegalArgumentException {
        if (rawUrl == null || rawUrl.trim().isEmpty()) {
            return "http://127.0.0.1:5000/";
        }
        String url = rawUrl.trim();
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        if (!url.endsWith("/")) {
            url += "/";
        }

        HttpUrl parsed = HttpUrl.parse(url);
        if (parsed == null) {
            throw new IllegalArgumentException("Địa chỉ máy chủ không hợp lệ: " + rawUrl);
        }
        return url;
    }

    public static synchronized SyncApiService createService(final ISyncPrefs prefs) {
        String baseUrl = normalizeAndValidateBaseUrl(prefs.getServerUrl());
        String token = prefs.getAuthToken() != null ? prefs.getAuthToken().trim() : "";

        // Tái sử dụng instance nếu URL và Token chưa thay đổi
        if (cachedService != null && baseUrl.equals(cachedBaseUrl) && token.equals(cachedToken)) {
            return cachedService;
        }

        HttpLoggingInterceptor logging = new HttpLoggingInterceptor();
        logging.setLevel(HttpLoggingInterceptor.Level.BODY);
        logging.redactHeader("Authorization"); // Bảo mật: Không in Bearer Token ra Logcat

        OkHttpClient client = new OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .writeTimeout(30, TimeUnit.SECONDS)
                .addInterceptor(new Interceptor() {
                    @Override
                    public Response intercept(Chain chain) throws IOException {
                        Request original = chain.request();
                        Request.Builder builder = original.newBuilder();

                        String currentToken = prefs.getAuthToken();
                        if (currentToken != null && !currentToken.trim().isEmpty()) {
                            builder.header("Authorization", "Bearer " + currentToken);
                        }
                        builder.header("Accept", "application/json");
                        builder.header("Content-Type", "application/json");

                        return chain.proceed(builder.build());
                    }
                })
                .addInterceptor(logging)
                .build();

        Retrofit retrofit = new Retrofit.Builder()
                .baseUrl(baseUrl)
                .client(client)
                .addConverterFactory(GsonConverterFactory.create())
                .build();

        cachedService = retrofit.create(SyncApiService.class);
        cachedBaseUrl = baseUrl;
        cachedToken = token;

        return cachedService;
    }

    public static synchronized void clearCache() {
        cachedService = null;
        cachedBaseUrl = null;
        cachedToken = null;
    }
}
