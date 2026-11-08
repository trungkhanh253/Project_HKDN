package com.iritech.irissample.sync.api;

import com.iritech.irissample.sync.data.ISyncPrefs;
import java.io.IOException;
import java.util.concurrent.TimeUnit;
import okhttp3.Interceptor;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

/**
 * Factory khởi tạo Retrofit API Service với Dynamic Base URL và Token từ ISyncPrefs
 */
public class SyncApiFactory {

    public static SyncApiService createService(final ISyncPrefs prefs) {
        String baseUrl = prefs.getServerUrl();
        if (baseUrl == null || baseUrl.trim().isEmpty()) {
            baseUrl = "http://127.0.0.1:5000/";
        }
        if (!baseUrl.endsWith("/")) {
            baseUrl += "/";
        }

        HttpLoggingInterceptor logging = new HttpLoggingInterceptor();
        logging.setLevel(HttpLoggingInterceptor.Level.BODY);

        OkHttpClient client = new OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .writeTimeout(30, TimeUnit.SECONDS)
                .addInterceptor(new Interceptor() {
                    @Override
                    public Response intercept(Chain chain) throws IOException {
                        Request original = chain.request();
                        Request.Builder builder = original.newBuilder();

                        String token = prefs.getAuthToken();
                        if (token != null && !token.trim().isEmpty()) {
                            builder.header("Authorization", "Bearer " + token);
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

        return retrofit.create(SyncApiService.class);
    }
}
