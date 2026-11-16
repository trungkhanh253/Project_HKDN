package com.iritech.irissample.sync.util;

/**
 * Interface ghi log độc lập với android.util.Log
 * Giúp chạy Unit Test trên máy tính (JVM) không bị crash "Method d in android.util.Log not mocked".
 */
public interface SyncLogger {
    void d(String tag, String message);
    void w(String tag, String message);
    void e(String tag, String message, Throwable throwable);

    /**
     * Logger mặc định in ra Console (dùng được cả trên JVM test và Android)
     */
    class ConsoleLogger implements SyncLogger {
        @Override
        public void d(String tag, String message) {
            System.out.println("[DEBUG][" + tag + "] " + message);
        }

        @Override
        public void w(String tag, String message) {
            System.out.println("[WARN][" + tag + "] " + message);
        }

        @Override
        public void e(String tag, String message, Throwable throwable) {
            System.err.println("[ERROR][" + tag + "] " + message + (throwable != null ? " : " + throwable.getMessage() : ""));
            if (throwable != null) {
                throwable.printStackTrace(System.err);
            }
        }
    }
}
