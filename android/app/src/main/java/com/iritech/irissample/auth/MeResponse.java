
package com.iritech.irissample.auth;

import com.google.gson.annotations.SerializedName;

public class MeResponse {

    @SerializedName("admin")
    public AdminInfo admin;

    public static class AdminInfo {

        @SerializedName("admin_id")
        public String adminId;

        @SerializedName("admin_code")
        public String adminCode;

        public String email;

        @SerializedName("full_name")
        public String fullName;

        public String role;

        public String uuid;

        @SerializedName("is_first_login")
        public int isFirstLogin;

        public String phone;

        public String gender;

        @SerializedName("date_of_birth")
        public String dateOfBirth;

        public String description;

        @SerializedName("has_iris")
        public int hasIris;
    }
}
