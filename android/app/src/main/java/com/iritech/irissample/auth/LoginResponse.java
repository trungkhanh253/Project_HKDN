
package com.iritech.irissample.auth;

import com.google.gson.annotations.SerializedName;

public class LoginResponse {

    @SerializedName("access_token")
    public String accessToken;

    @SerializedName("refresh_token")
    public String refreshToken;

    @SerializedName("token_type")
    public String tokenType;

    @SerializedName("expires_in")
    public int expiresIn;

    @SerializedName("admin")
    public AdminInfo admin;

    public static class AdminInfo {

        @SerializedName("admin_id")
        public String adminId;

        public String email;

        @SerializedName("full_name")
        public String fullName;

        public String role;

        public String uuid;

        @SerializedName("is_first_login")
        public int isFirstLogin;
    }
}
