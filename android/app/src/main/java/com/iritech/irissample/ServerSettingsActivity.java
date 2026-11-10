
package com.iritech.irissample;

import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.iritech.irissample.sync.data.AndroidSyncPrefs;
import com.iritech.irissample.sync.api.SyncApiFactory;

import java.net.HttpURLConnection;
import java.net.URL;

import android.widget.RadioButton;
import com.iritech.irissample.sync.worker.SyncWorkScheduler;

import android.widget.Switch;
import androidx.work.WorkManager;
import androidx.lifecycle.LiveData;
import androidx.work.WorkInfo;

import java.util.List;

public class ServerSettingsActivity extends AppCompatActivity {

    private EditText editServerUrl;
    private TextView txtConnectionStatus;
    private AndroidSyncPrefs prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_server_settings);

        prefs = new AndroidSyncPrefs(this);

        Switch switchAutoSync = findViewById(R.id.switchAutoSync);

        TextView txtAutoSyncStatus =
                findViewById(R.id.txtAutoSyncStatus);

        observeAutoSyncStatus(txtAutoSyncStatus);

        RadioButton radioStandalone =
                findViewById(R.id.radioStandalone);

        RadioButton radioServer =
                findViewById(R.id.radioServer);

        // Hiển thị chế độ đã lưu
        if (prefs.isServerMode()) {
            radioServer.setChecked(true);
        } else {
            radioStandalone.setChecked(true);
        }

        // Lưu chế độ khi người dùng chọn
        radioStandalone.setOnClickListener(v -> {
            prefs.setServerMode(false);
            prefs.setAutoSyncEnabled(false);

            switchAutoSync.setChecked(false);

            SyncWorkScheduler.cancelAllSync(
                    getApplicationContext()
            );

            Toast.makeText(
                    this,
                    "Đã chuyển sang Standalone Mode",
                    Toast.LENGTH_SHORT
            ).show();
        });

        radioServer.setOnClickListener(v -> {
            prefs.setServerMode(true);

            Toast.makeText(
                    this,
                    "Đã chuyển sang Server Mode",
                    Toast.LENGTH_SHORT
            ).show();
        });


        editServerUrl = findViewById(R.id.editServerUrl);
        txtConnectionStatus = findViewById(R.id.txtConnectionStatus);

        Button btnSaveServer = findViewById(R.id.btnSaveServer);
        Button btnTestConnection = findViewById(R.id.btnTestConnection);

        Button btnSyncNow = findViewById(R.id.btnSyncNow);
        TextView txtSyncStatus = findViewById(R.id.txtSyncStatus);

        observeSyncStatus(txtSyncStatus);

        String savedUrl = prefs.getServerUrl();
        editServerUrl.setText(savedUrl.isEmpty()
                ? "http://10.0.2.2:5000/"
                : savedUrl);

        btnSaveServer.setOnClickListener(v -> {
            try {
                String url = validateUrl();
                String oldUrl = SyncApiFactory.normalizeAndValidateBaseUrl(
                        prefs.getServerUrl()
                );

                if (!url.equals(oldUrl)) {
                    SyncWorkScheduler.cancelAllSync(getApplicationContext());
                    prefs.setAutoSyncEnabled(false);
                    switchAutoSync.setChecked(false);
                    prefs.clearAuthSession();
                }

                prefs.setServerUrl(url);
                SyncApiFactory.clearCache();

                Toast.makeText(this,
                        "Đã lưu cấu hình máy chủ",
                        Toast.LENGTH_SHORT).show();
            } catch (IllegalArgumentException e) {
                editServerUrl.setError(e.getMessage());
            }
        });

        btnTestConnection.setOnClickListener(v -> testConnection());


        btnSyncNow.setOnClickListener(v -> {
            if (!prefs.isServerMode()) {
                txtSyncStatus.setText("Vui lòng bật Server Mode");
                Toast.makeText(this,
                        "Chỉ đồng bộ khi sử dụng Server Mode",
                        Toast.LENGTH_SHORT).show();
                return;
            }

            String token = prefs.getAuthToken();

            if (token == null || token.trim().isEmpty()) {
                txtSyncStatus.setText("Chưa đăng nhập Server");
                Toast.makeText(this,
                        "Cần đăng nhập Server trước khi đồng bộ",
                        Toast.LENGTH_SHORT).show();
                return;
            }

            txtSyncStatus.setText("Đang gửi yêu cầu đồng bộ...");

            try {
                SyncWorkScheduler.triggerImmediateSync(
                        getApplicationContext()
                );

                txtSyncStatus.setText(
                        "Đã gửi yêu cầu đồng bộ. Đang chờ xử lý."
                );

            } catch (Exception e) {
                txtSyncStatus.setText(
                        "Không thể yêu cầu đồng bộ: " + e.getMessage()
                );
            }
        });


        switchAutoSync.setChecked(prefs.isAutoSyncEnabled());

        switchAutoSync.setOnCheckedChangeListener((buttonView, isChecked) -> {

            if (!isChecked) {
                WorkManager.getInstance(getApplicationContext())
                        .cancelUniqueWork(
                                SyncWorkScheduler.PERIODIC_WORK_NAME
                        );

                prefs.setAutoSyncEnabled(false);

                Toast.makeText(this,
                        "Đã tắt tự động đồng bộ",
                        Toast.LENGTH_SHORT).show();
                return;
            }

            if (!prefs.isServerMode()) {
                switchAutoSync.setChecked(false);

                Toast.makeText(this,
                        "Vui lòng bật Server Mode",
                        Toast.LENGTH_SHORT).show();
                return;
            }

            String token = prefs.getAuthToken();

            if (token == null || token.trim().isEmpty()) {
                switchAutoSync.setChecked(false);

                Toast.makeText(this,
                        "Cần đăng nhập Server trước khi bật Auto Sync",
                        Toast.LENGTH_SHORT).show();
                return;
            }

            try {
                SyncWorkScheduler.schedulePeriodicSync(
                        getApplicationContext()
                );

                prefs.setAutoSyncEnabled(true);

                Toast.makeText(this,
                        "Đã lên lịch tự động đồng bộ",
                        Toast.LENGTH_SHORT).show();

            } catch (Exception e) {
                switchAutoSync.setChecked(false);

                Toast.makeText(this,
                        "Không thể bật Auto Sync: " + e.getMessage(),
                        Toast.LENGTH_LONG).show();
            }
        });

    }


    private void observeAutoSyncStatus(TextView txtAutoSyncStatus) {

        WorkManager.getInstance(getApplicationContext())
                .getWorkInfosForUniqueWorkLiveData(
                        SyncWorkScheduler.PERIODIC_WORK_NAME
                )
                .observe(this, workInfos -> {

                    if (workInfos == null || workInfos.isEmpty()) {
                        txtAutoSyncStatus.setText(
                                "Chưa có lịch tự động đồng bộ"
                        );
                        return;
                    }

                    boolean hasActiveWork = false;
                    boolean isRunning = false;

                    for (WorkInfo info : workInfos) {
                        if (info.getState() == WorkInfo.State.RUNNING) {
                            isRunning = true;
                        }

                        if (info.getState() == WorkInfo.State.ENQUEUED
                                || info.getState() == WorkInfo.State.RUNNING) {
                            hasActiveWork = true;
                        }
                    }

                    if (isRunning) {
                        txtAutoSyncStatus.setText(
                                "Auto Sync đang thực hiện đồng bộ..."
                        );
                    } else if (hasActiveWork) {
                        txtAutoSyncStatus.setText(
                                "Đã lên lịch Auto Sync (chu kỳ 15 phút)"
                        );
                    } else {
                        txtAutoSyncStatus.setText(
                                "Auto Sync hiện không có lịch hoạt động"
                        );
                    }
                });
    }


    private void observeSyncStatus(TextView txtSyncStatus) {

        WorkManager.getInstance(getApplicationContext())
                .getWorkInfosForUniqueWorkLiveData(
                        SyncWorkScheduler.ONE_TIME_WORK_NAME
                )
                .observe(this, workInfos -> {

                    if (workInfos == null || workInfos.isEmpty()) {
                        txtSyncStatus.setText("Chưa có yêu cầu đồng bộ");
                        return;
                    }

                    WorkInfo latestWork = workInfos.get(
                            workInfos.size() - 1
                    );

                    WorkInfo.State state = latestWork.getState();

                    switch (state) {
                        case ENQUEUED:
                            txtSyncStatus.setText(
                                    "Đang chờ WorkManager xử lý..."
                            );
                            break;

                        case RUNNING:
                            txtSyncStatus.setText(
                                    "Đang thực hiện đồng bộ..."
                            );
                            break;

                        case SUCCEEDED:
                            txtSyncStatus.setText(
                                    "Worker đã hoàn thành thành công"
                            );
                            break;

                        case FAILED:
                            txtSyncStatus.setText(
                                    "Đồng bộ thất bại. Kiểm tra Logcat."
                            );
                            break;

                        case CANCELLED:
                            txtSyncStatus.setText(
                                    "Yêu cầu đồng bộ đã bị hủy"
                            );
                            break;

                        case BLOCKED:
                            txtSyncStatus.setText(
                                    "Đang chờ tác vụ đồng bộ trước đó"
                            );
                            break;
                    }
                });
    }


    private String validateUrl() {
        String raw = editServerUrl.getText().toString().trim();

        if (raw.isEmpty()) {
            throw new IllegalArgumentException("Vui lòng nhập Server URL");
        }

        return SyncApiFactory.normalizeAndValidateBaseUrl(raw);
    }

    private void testConnection() {
        final String baseUrl;

        try {
            baseUrl = validateUrl();
        } catch (IllegalArgumentException e) {
            editServerUrl.setError(e.getMessage());
            return;
        }

        txtConnectionStatus.setText("Đang kiểm tra kết nối...");

        new Thread(() -> {
            HttpURLConnection connection = null;
            String result;

            try {
                URL url = new URL(baseUrl + "health");
                connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod("GET");
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(5000);

                int status = connection.getResponseCode();

                if (status >= 200 && status < 300) {
                    result = "Kết nối thành công (HTTP " + status + ")";
                } else {
                    result = "Máy chủ phản hồi HTTP " + status;
                }
            } catch (Exception e) {
                result = "Kết nối thất bại: " + e.getMessage();
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }

            final String message = result;
            runOnUiThread(() -> txtConnectionStatus.setText(message));

        }).start();
    }
}
