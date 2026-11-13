
package com.iritech.irissample.sync.data;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import com.iritech.irissample.DatabaseHelper;
import com.iritech.irissample.sync.model.SyncChange;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.util.ArrayList;
import java.util.List;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import com.google.gson.JsonElement;

public class SQLiteSyncRepository implements SyncRepository {

    private static final int MAX_RETRIES = 5;

    private final DatabaseHelper dbHelper;

    private static final Set<String> SYNC_TABLES =
            new HashSet<>(Arrays.asList(
                    "admin",
                    "subjects",
                    "students",
                    "enrollments",
                    "checkin_history",
                    "email_recipients"
            ));

    public SQLiteSyncRepository(Context context) {
        this.dbHelper = new DatabaseHelper(
                context.getApplicationContext()
        );
    }

    @Override
    public long getLastSeq() {
        return dbHelper.getLastSeq();
    }

    @Override
    public void setLastSeq(long seq) {
        dbHelper.setLastSeq(seq);
    }


    @Override
    public List<SyncChange> getPendingChanges(int limit) {
        List<SyncChange> changes = new ArrayList<>();

        if (limit <= 0) {
            return changes;
        }

        SQLiteDatabase db = dbHelper.getReadableDatabase();

        String sql =
                "SELECT change_id, uuid, table_name, operation, " +
                        "payload, updated_at " +
                        "FROM sync_outbox " +
                        "WHERE status = 'PENDING' " +
                        "ORDER BY change_id ASC " +
                        "LIMIT ?";

        try (Cursor cursor = db.rawQuery(
                sql,
                new String[]{String.valueOf(limit)}
        )) {
            while (cursor.moveToNext()) {

                String changeId = cursor.getString(0);
                String uuid = cursor.getString(1);
                String tableName = cursor.getString(2);
                String operation = cursor.getString(3);
                String payloadText = cursor.getString(4);
                long updatedAt = cursor.getLong(5);

                JsonObject payload = null;

                if (!"DELETE".equalsIgnoreCase(operation)) {

                    if (payloadText != null &&
                            !payloadText.trim().isEmpty()) {

                        payload = new JsonParser().parse(payloadText).getAsJsonObject();

                    } else {
                        payload = loadPayload(
                                db,
                                tableName,
                                uuid
                        );
                    }

                    if (payload == null) {
                        // Bản ghi không còn trong SQLite.
                        // Không gửi payload rỗng lên server.
                        android.util.Log.w(
                                "SYNC_REPO",
                                "Missing payload for change_id=" + changeId
                        );
                        continue;
                    }
                    payload = sanitizePushPayload(tableName, payload);
                }

                SyncChange change = new SyncChange(
                        changeId,
                        uuid,
                        tableName,
                        operation,
                        payload,
                        updatedAt
                );

                changes.add(change);
            }
        }

        return changes;
    }


    @Override
    public int getPendingCount() {
        return countByStatus("PENDING");
    }

    @Override
    public int getFailedCount() {
        return countByStatus("FAILED");
    }

    private int countByStatus(String status) {

        SQLiteDatabase db = dbHelper.getReadableDatabase();

        try (Cursor cursor = db.rawQuery(
                "SELECT COUNT(*) FROM sync_outbox WHERE status = ?",
                new String[]{status}
        )) {
            if (cursor.moveToFirst()) {
                return cursor.getInt(0);
            }
        }

        return 0;
    }

    @Override
    public void enqueueAllForSync() {
        dbHelper.enqueueAllForSync();
    }


    @Override
    public void markSynced(List<String> changeIds) {
        if (changeIds == null || changeIds.isEmpty()) return;

        SQLiteDatabase db = dbHelper.getWritableDatabase();
        db.beginTransaction();

        try {
            for (String changeId : changeIds) {
                db.delete(
                        "sync_outbox",
                        "change_id = ? AND status = 'PENDING'",
                        new String[]{changeId}
                );
            }

            db.setTransactionSuccessful();
        } finally {
            db.endTransaction();
        }
    }

    @Override
    public void markFailed(
            List<String> changeIds,
            String errorMessage
    ) {
        if (changeIds == null || changeIds.isEmpty()) return;

        SQLiteDatabase db = dbHelper.getWritableDatabase();
        db.beginTransaction();

        try {
            for (String changeId : changeIds) {
                ContentValues values = new ContentValues();
                values.put("status", "FAILED");
                values.put("last_error", errorMessage);

                db.update(
                        "sync_outbox",
                        values,
                        "change_id = ? AND status = 'PENDING'",
                        new String[]{changeId}
                );
            }

            db.setTransactionSuccessful();
        } finally {
            db.endTransaction();
        }
    }

    @Override
    public void recordBatchFailure(
            List<String> changeIds,
            String errorMessage
    ) {
        if (changeIds == null || changeIds.isEmpty()) return;

        SQLiteDatabase db = dbHelper.getWritableDatabase();
        db.beginTransaction();

        try {
            for (String changeId : changeIds) {
                db.execSQL(
                        "UPDATE sync_outbox " +
                                "SET retry_count = retry_count + 1, " +
                                "last_error = ?, " +
                                "status = CASE " +
                                "WHEN retry_count + 1 >= ? THEN 'FAILED' " +
                                "ELSE 'PENDING' END " +
                                "WHERE change_id = ? AND status = 'PENDING'",
                        new Object[]{
                                errorMessage,
                                MAX_RETRIES,
                                changeId
                        }
                );
            }

            db.setTransactionSuccessful();
        } finally {
            db.endTransaction();
        }
    }




    @Override
    public void applyPulledChanges(
            List<SyncChange> changes,
            long newSeq
    ) {
        if (changes == null) {
            throw new IllegalArgumentException(
                    "changes cannot be null"
            );
        }

        SQLiteDatabase db = dbHelper.getWritableDatabase();
        db.beginTransaction();

        try {
            long currentSeq = 0;

            try (Cursor cursor = db.rawQuery(
                    "SELECT meta_value FROM sync_meta " +
                            "WHERE meta_key = 'last_seq'",
                    null
            )) {
                if (cursor.moveToFirst()) {
                    currentSeq = Long.parseLong(cursor.getString(0));
                }
            }

            if (newSeq < currentSeq) {
                throw new IllegalArgumentException(
                        "newSeq cannot be smaller than currentSeq"
                );
            }

            long previousSeq = currentSeq;

            // Kiểm tra thứ tự các thay đổi trước khi ghi SQLite
            for (SyncChange change : changes) {
                if (change == null || !change.isValidChange()) {
                    throw new IllegalArgumentException(
                            "Invalid pulled change"
                    );
                }

                Long seq = change.getSeq();

                if (seq == null ||
                        seq <= previousSeq ||
                        seq > newSeq) {
                    throw new IllegalArgumentException(
                            "Invalid pull sequence: " + seq
                    );
                }

                previousSeq = seq;
            }

            if (!changes.isEmpty() && previousSeq != newSeq) {
                throw new IllegalArgumentException(
                        "newSeq does not match last change seq"
                );
            }

            // Chặn trigger tạo outbox khi Pull
            ContentValues suppression = new ContentValues();
            suppression.put("is_suppressed", 1);

            int affected = db.update(
                    "sync_state",
                    suppression,
                    "id = 1",
                    null
            );

            if (affected != 1) {
                throw new IllegalStateException(
                        "sync_state is not initialized"
                );
            }

            // Áp dụng các thay đổi theo thứ tự server trả về
            for (SyncChange change : changes) {
                String table = change.getTableName();

                if (!SYNC_TABLES.contains(table)) {
                    throw new IllegalArgumentException(
                            "Unsupported table: " + table
                    );
                }

                if (hasLocalPendingChange(
                        db,
                        table,
                        change.getUuid()
                )) {
                    throw new IllegalStateException(
                            "Local changes must be resolved before Pull: "
                                    + table + "/" + change.getUuid()
                    );
                }

                if (change.isDelete()) {
                    deleteRemoteChange(db, change);
                } else {
                    upsertRemoteChange(db, change);
                }
            }

            // Lưu last_seq trong cùng transaction
            ContentValues meta = new ContentValues();
            meta.put("meta_key", "last_seq");
            meta.put("meta_value", String.valueOf(newSeq));

            db.insertWithOnConflict(
                    "sync_meta",
                    null,
                    meta,
                    SQLiteDatabase.CONFLICT_REPLACE
            );

            // Bật lại trigger
            suppression.put("is_suppressed", 0);

            db.update(
                    "sync_state",
                    suppression,
                    "id = 1",
                    null
            );

            db.setTransactionSuccessful();

        } finally {
            db.endTransaction();
        }
    }




    private JsonObject loadPayload(
            SQLiteDatabase db,
            String tableName,
            String uuid
    ) {
        if (!SYNC_TABLES.contains(tableName)) {
            throw new IllegalArgumentException(
                    "Unsupported sync table: " + tableName
            );
        }

        try (Cursor cursor = db.query(
                tableName,
                null,
                "uuid = ?",
                new String[]{uuid},
                null,
                null,
                null,
                "1"
        )) {
            if (!cursor.moveToFirst()) {
                return null;
            }

            return cursorToJson(cursor);
        }
    }

    private JsonObject cursorToJson(Cursor cursor) {
        JsonObject json = new JsonObject();

        for (int i = 0; i < cursor.getColumnCount(); i++) {
            String column = cursor.getColumnName(i);

            switch (cursor.getType(i)) {
                case Cursor.FIELD_TYPE_NULL:
                    json.add(column, JsonNull.INSTANCE);
                    break;

                case Cursor.FIELD_TYPE_INTEGER:
                    json.addProperty(column, cursor.getLong(i));
                    break;

                case Cursor.FIELD_TYPE_FLOAT:
                    json.addProperty(column, cursor.getDouble(i));
                    break;

                case Cursor.FIELD_TYPE_STRING:
                    json.addProperty(column, cursor.getString(i));
                    break;

                case Cursor.FIELD_TYPE_BLOB:
                    // Không tự động đồng bộ BLOB.
                    // Cần quy định định dạng riêng nếu server hỗ trợ.
                    break;
            }
        }

        return json;
    }


    private void validatePushPayload(
            String tableName,
            JsonObject payload
    ) {
        if (payload == null) {
            return;
        }

        if (payload.has("password")
                || payload.has("reset_token")
                || payload.has("checkin_password")
                || payload.has("face_embedding")) {
            throw new IllegalStateException(
                    "Payload contains restricted fields: " + tableName
            );
        }
    }

    private void deleteRemoteChange(
            SQLiteDatabase db,
            SyncChange change
    ) {
        db.delete(
                change.getTableName(),
                "uuid = ?",
                new String[]{change.getUuid()}
        );
    }


    private void upsertRemoteChange(
            SQLiteDatabase db,
            SyncChange change
    ) {
        String table = change.getTableName();
        String uuid = change.getUuid();
        JsonObject payload = change.getPayload();

        if (!SYNC_TABLES.contains(table)) {
            throw new IllegalArgumentException(
                    "Unsupported sync table: " + table
            );
        }

        if (uuid == null || uuid.trim().isEmpty() || payload == null) {
            throw new IllegalArgumentException(
                    "Missing uuid or payload"
            );
        }

        // Kiểm tra dữ liệu đã tồn tại theo UUID chưa
        boolean exists;

        try (Cursor cursor = db.query(
                table,
                new String[]{"uuid"},
                "uuid = ?",
                new String[]{uuid},
                null,
                null,
                null
        )) {
            exists = cursor.moveToFirst();
        }

        // Chỉ lấy các cột thật sự tồn tại trong SQLite
        Set<String> allowedColumns = getTableColumns(db, table);

        ContentValues values = new ContentValues();

        for (String key : payload.keySet()) {

            if (!allowedColumns.contains(key)) {
                continue;
            }

            // Không nhận mật khẩu hoặc token từ dữ liệu sync
            if (isRestrictedColumn(key)) {
                continue;
            }

            // UUID và thời gian lấy từ SyncChange
            if ("uuid".equals(key) || "updated_at".equals(key)) {
                continue;
            }

            JsonElement element = payload.get(key);

            if (element == null || element.isJsonNull()) {
                values.putNull(key);
            } else if (element.isJsonPrimitive()) {
                if (element.getAsJsonPrimitive().isBoolean()) {
                    values.put(key, element.getAsBoolean() ? 1 : 0);
                } else if (element.getAsJsonPrimitive().isNumber()) {
                    String number = element.getAsString();

                    if (number.matches("-?\\d+")) {
                        values.put(key, Long.parseLong(number));
                    } else {
                        values.put(key, Double.parseDouble(number));
                    }
                } else {
                    values.put(key, element.getAsString());
                }
            } else {
                throw new IllegalArgumentException(
                        "Unsupported JSON value for column: " + key
                );
            }
        }

        values.put("uuid", uuid);
        values.put("updated_at", change.getUpdatedAt());

        if (exists) {
            int updated = db.update(
                    table,
                    values,
                    "uuid = ?",
                    new String[]{uuid}
            );

            if (updated != 1) {
                throw new IllegalStateException(
                        "Failed to update " + table + ": " + uuid
                );
            }

        } else {
            long inserted = db.insertOrThrow(
                    table,
                    null,
                    values
            );

            if (inserted == -1) {
                throw new IllegalStateException(
                        "Failed to insert " + table + ": " + uuid
                );
            }
        }
    }
    private Set<String> getTableColumns(
            SQLiteDatabase db,
            String table
    ) {
        Set<String> columns = new HashSet<>();

        try (Cursor cursor = db.rawQuery(
                "PRAGMA table_info(" + table + ")",
                null
        )) {
            int nameIndex = cursor.getColumnIndexOrThrow("name");

            while (cursor.moveToNext()) {
                columns.add(cursor.getString(nameIndex));
            }
        }

        return columns;
    }
    private boolean isRestrictedColumn(String column) {
        return "password".equals(column)
                || "reset_token".equals(column)
                || "checkin_password".equals(column)
                || "face_embedding".equals(column);
    }

    private boolean hasLocalPendingChange(
            SQLiteDatabase db,
            String table,
            String uuid
    ) {
        try (Cursor cursor = db.rawQuery(
                "SELECT 1 FROM sync_outbox " +
                        "WHERE table_name = ? AND uuid = ? " +
                        "AND status IN ('PENDING', 'FAILED') " +
                        "LIMIT 1",
                new String[]{table, uuid}
        )) {
            return cursor.moveToFirst();
        }
    }
    private JsonObject sanitizePushPayload(
            String tableName,
            JsonObject payload
    ) {
        if (payload == null) {
            throw new IllegalArgumentException(
                    "Payload cannot be null: " + tableName
            );
        }

        JsonObject sanitized = payload.deepCopy();

        sanitized.remove("password");
        sanitized.remove("reset_token");
        sanitized.remove("checkin_password");
        sanitized.remove("face_embedding");

        return sanitized;
    }
}
