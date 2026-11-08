package com.iritech.irissample.sync.util;

/**
 * Tiện ích ánh xạ tên bảng giữa Android SQLite và Server Backend
 * Đảm bảo 6 bảng đồng bộ đúng dù Server dùng số ít (student) hay số nhiều (students).
 */
public class TableMapper {

    public static String toServerTableName(String localTableName) {
        if (localTableName == null) return "";
        String clean = localTableName.trim().toLowerCase();
        switch (clean) {
            case "students":
                return "students"; // hoặc "student" tùy backend
            case "subjects":
                return "subjects";
            case "enrollments":
                return "enrollments";
            case "checkin_history":
                return "checkin_history";
            case "email_recipients":
                return "email_recipients";
            case "admin":
            default:
                return clean;
        }
    }

    public static String toLocalTableName(String serverTableName) {
        if (serverTableName == null) return "";
        String clean = serverTableName.trim().toLowerCase();
        switch (clean) {
            case "student":
            case "students":
                return "students";
            case "subject":
            case "subjects":
                return "subjects";
            case "enrollment":
            case "enrollments":
                return "enrollments";
            case "checkin_history":
                return "checkin_history";
            case "email_recipient":
            case "email_recipients":
                return "email_recipients";
            case "admin":
            default:
                return clean;
        }
    }
}
