package com.iritech.irissample.sync.util;

import android.util.Log;

/**
 * Logger chạy trên môi trường Android thật (sử dụng android.util.Log)
 */
public class AndroidLogger implements SyncLogger {

    @Override
    public void d(String tag, String message) {
        Log.d(tag, message);
    }

    @Override
    public void w(String tag, String message) {
        Log.w(tag, message);
    }

    @Override
    public void e(String tag, String message, Throwable throwable) {
        if (throwable != null) {
            Log.e(tag, message, throwable);
        } else {
            Log.e(tag, message);
        }
    }
}
