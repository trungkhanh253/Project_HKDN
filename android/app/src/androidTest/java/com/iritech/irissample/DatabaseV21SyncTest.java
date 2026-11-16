package com.iritech.irissample;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

import static org.junit.Assert.*;

/**
 * Kiểm thử phần dữ liệu đồng bộ của Android (DB v21): migration, trigger, outbox, cờ chặn.
 * Chạy trên thiết bị/giả lập: Android Studio -> chuột phải file -> Run.
 */
@RunWith(AndroidJUnit4.class)
public class DatabaseV21SyncTest {

    private static final String DB_NAME = "attendance.db";

    /** Schema v20 gốc (6 bảng), dùng để dựng DB cũ rồi nâng cấp lên v21. */
    private static final String[] V20_DDL = {
            "CREATE TABLE admin (admin_id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, full_name TEXT NOT NULL, date_of_birth TEXT, phone TEXT, gender TEXT, photo_path TEXT, description TEXT, role TEXT NOT NULL DEFAULT 'ADMIN', admin_code TEXT, reset_token TEXT, expire_at INTEGER, is_first_login INTEGER DEFAULT 1, has_iris INTEGER DEFAULT 0)",
            "CREATE TABLE subjects (subject_id TEXT PRIMARY KEY, subject_name TEXT NOT NULL, time_slot TEXT, created_by TEXT, instructor_id TEXT, subject_status TEXT NOT NULL DEFAULT 'UNASSIGNED', created_at TEXT, semester_start_date TEXT, semester_end_date TEXT, FOREIGN KEY(created_by) REFERENCES admin(admin_id) ON DELETE SET NULL, FOREIGN KEY(instructor_id) REFERENCES admin(admin_id) ON DELETE SET NULL);",
            "CREATE TABLE students (student_id TEXT PRIMARY KEY, full_name TEXT, email TEXT, phone TEXT, photo_path TEXT, checkin_password TEXT);",
            "CREATE TABLE enrollments (student_id TEXT, subject_id TEXT, enrollment_status TEXT, PRIMARY KEY (student_id, subject_id), FOREIGN KEY(student_id) REFERENCES students(student_id), FOREIGN KEY(subject_id) REFERENCES subjects(subject_id));",
            "CREATE TABLE checkin_history (checkin_id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT, subject_id TEXT, checkin_time TEXT, checkin_date TEXT, FOREIGN KEY(student_id) REFERENCES students(student_id), FOREIGN KEY(subject_id) REFERENCES subjects(subject_id));",
            "CREATE TABLE email_recipients (email_id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id TEXT NOT NULL, email_address TEXT NOT NULL, recipient_name TEXT, added_date TEXT, UNIQUE(subject_id, email_address), FOREIGN KEY(subject_id) REFERENCES subjects(subject_id) ON DELETE CASCADE);"
    };

    private Context context;

    @Before
    public void setUp() {
        context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        context.deleteDatabase(DB_NAME);
    }

    @After
    public void tearDown() {
        context.deleteDatabase(DB_NAME);
    }

    // ---------- tiện ích ----------
    private long count(SQLiteDatabase db, String sql) {
        Cursor c = db.rawQuery(sql, null);
        try { c.moveToFirst(); return c.getLong(0); } finally { c.close(); }
    }

    /** Dựng DB v20 có dữ liệu (đặt user_version = 20 rồi đóng). */
    private void createV20WithData() {
        SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(DB_NAME), null);
        for (String s : V20_DDL) db.execSQL(s);
        db.execSQL("INSERT INTO admin(admin_id,email,password,full_name,role) VALUES('A1','a@x.com','h','Admin','SUPER_ADMIN')");
        db.execSQL("INSERT INTO subjects(subject_id,subject_name,created_by) VALUES('M1','Toan','A1')");
        db.execSQL("INSERT INTO students(student_id,full_name) VALUES('S1','An'),('S2','Binh')");
        db.execSQL("INSERT INTO enrollments(student_id,subject_id) VALUES('S1','M1'),('S2','M1')");
        db.execSQL("INSERT INTO checkin_history(student_id,subject_id) VALUES('S1','M1')");
        db.execSQL("INSERT INTO email_recipients(subject_id,email_address) VALUES('M1','t@x.com')");
        db.setVersion(20);
        db.close();
    }

    // ---------- các ca test ----------

    @Test
    public void upgradeFromV20_keepsAllData_andFillsUuid() {
        createV20WithData();

        DatabaseHelper helper = new DatabaseHelper(context);
        SQLiteDatabase db = helper.getWritableDatabase();

        assertTrue(db.getVersion() >= 21);
        assertEquals(1, count(db, "SELECT COUNT(*) FROM admin"));
        assertEquals(1, count(db, "SELECT COUNT(*) FROM subjects"));
        assertEquals(2, count(db, "SELECT COUNT(*) FROM students"));
        assertEquals(2, count(db, "SELECT COUNT(*) FROM enrollments"));
        assertEquals(1, count(db, "SELECT COUNT(*) FROM checkin_history"));
        assertEquals(1, count(db, "SELECT COUNT(*) FROM email_recipients"));

        assertEquals(0, count(db, "SELECT COUNT(*) FROM students WHERE uuid IS NULL"));
        assertEquals(2, count(db, "SELECT COUNT(DISTINCT uuid) FROM students"));
        assertEquals("nâng cấp không được sinh outbox", 0, count(db, "SELECT COUNT(*) FROM sync_outbox"));
        assertEquals(0, count(db, "SELECT is_suppressed FROM sync_state WHERE id=1"));
        assertEquals(0, helper.getLastSeq());
        helper.close();
    }

    @Test
    public void insert_withoutUuid_getsUuid_andWritesOutbox() {
        DatabaseHelper helper = new DatabaseHelper(context);
        SQLiteDatabase db = helper.getWritableDatabase();

        db.execSQL("INSERT INTO students(student_id,full_name) VALUES('S1','An')");

        assertEquals(1, count(db, "SELECT COUNT(*) FROM students WHERE uuid IS NOT NULL AND updated_at > 0"));
        assertEquals(1, count(db, "SELECT COUNT(*) FROM sync_outbox WHERE table_name='students' AND operation='INSERT' AND status='PENDING'"));
        helper.close();
    }

    @Test
    public void update_bumpsUpdatedAt_keepsUuid_andWritesOutbox() throws Exception {
        DatabaseHelper helper = new DatabaseHelper(context);
        SQLiteDatabase db = helper.getWritableDatabase();
        db.execSQL("INSERT INTO students(student_id,full_name) VALUES('S1','An')");
        Cursor c = db.rawQuery("SELECT uuid, updated_at FROM students WHERE student_id='S1'", null);
        c.moveToFirst();
        String uuid = c.getString(0);
        long t0 = c.getLong(1);
        c.close();
        db.execSQL("DELETE FROM sync_outbox");
        Thread.sleep(1100);

        db.execSQL("UPDATE students SET full_name='An2' WHERE student_id='S1'");

        c = db.rawQuery("SELECT uuid, updated_at FROM students WHERE student_id='S1'", null);
        c.moveToFirst();
        assertEquals(uuid, c.getString(0));
        assertTrue(c.getLong(1) > t0);
        c.close();
        assertEquals(1, count(db, "SELECT COUNT(*) FROM sync_outbox WHERE operation='UPDATE'"));
        helper.close();
    }

    @Test
    public void delete_writesTombstone() {
        DatabaseHelper helper = new DatabaseHelper(context);
        SQLiteDatabase db = helper.getWritableDatabase();
        db.execSQL("INSERT INTO students(student_id,full_name) VALUES('S1','An')");
        db.execSQL("DELETE FROM sync_outbox");

        db.execSQL("DELETE FROM students WHERE student_id='S1'");

        assertEquals(1, count(db, "SELECT COUNT(*) FROM sync_outbox WHERE table_name='students' AND operation='DELETE'"));
        helper.close();
    }

    @Test
    public void tablesWithAutoIncrementKey_alsoWriteOutbox() {
        DatabaseHelper helper = new DatabaseHelper(context);
        SQLiteDatabase db = helper.getWritableDatabase();
        db.execSQL("INSERT INTO subjects(subject_id,subject_name) VALUES('M1','Toan')");
        db.execSQL("INSERT INTO students(student_id,full_name) VALUES('S1','An')");
        db.execSQL("DELETE FROM sync_outbox");

        db.execSQL("INSERT INTO checkin_history(student_id,subject_id) VALUES('S1','M1')");
        db.execSQL("INSERT INTO email_recipients(subject_id,email_address) VALUES('M1','t@x.com')");

        assertEquals(1, count(db, "SELECT COUNT(*) FROM sync_outbox WHERE table_name='checkin_history'"));
        assertEquals(1, count(db, "SELECT COUNT(*) FROM sync_outbox WHERE table_name='email_recipients'"));
        helper.close();
    }

    @Test
    public void applyRemote_suppressesTriggers_andRestoresFlag() {
        final DatabaseHelper helper = new DatabaseHelper(context);
        final SQLiteDatabase db = helper.getWritableDatabase();

        helper.applyRemote(new Runnable() {
            @Override public void run() {
                db.execSQL("INSERT INTO students(student_id,full_name,uuid,updated_at) VALUES('S9','Remote','u-9',5)");
                db.execSQL("UPDATE students SET full_name='R2' WHERE student_id='S9'");
            }
        });

        assertEquals("dữ liệu kéo về không được vào outbox", 0, count(db, "SELECT COUNT(*) FROM sync_outbox"));
        assertEquals("uuid từ server phải được giữ", 1, count(db, "SELECT COUNT(*) FROM students WHERE uuid='u-9'"));
        assertEquals("cờ chặn phải được tắt lại", 0, count(db, "SELECT is_suppressed FROM sync_state WHERE id=1"));

        db.execSQL("INSERT INTO students(student_id,full_name) VALUES('S10','Local')");
        assertEquals(1, count(db, "SELECT COUNT(*) FROM sync_outbox"));
        helper.close();
    }

    @Test
    public void applyRemote_exceptionStillResetsFlag() {
        final DatabaseHelper helper = new DatabaseHelper(context);
        SQLiteDatabase db = helper.getWritableDatabase();
        try {
            helper.applyRemote(new Runnable() {
                @Override public void run() { throw new IllegalStateException("lỗi giả lập"); }
            });
            fail("phải ném lỗi");
        } catch (IllegalStateException expected) { }
        assertEquals(0, count(db, "SELECT is_suppressed FROM sync_state WHERE id=1"));
        helper.close();
    }

    @Test
    public void enqueueAllForSync_isIdempotent_andResetAfterRestoreClearsLastSeq() {
        DatabaseHelper helper = new DatabaseHelper(context);
        SQLiteDatabase db = helper.getWritableDatabase();
        db.execSQL("INSERT INTO students(student_id,full_name) VALUES('S1','An'),('S2','Binh')");
        db.execSQL("DELETE FROM sync_outbox");
        helper.setLastSeq(120);
        assertEquals(120, helper.getLastSeq());

        helper.enqueueAllForSync();
        helper.enqueueAllForSync();
        assertEquals(2, count(db, "SELECT COUNT(*) FROM sync_outbox WHERE table_name='students' AND status='PENDING'"));

        helper.resetSyncAfterRestore();
        assertEquals(0, helper.getLastSeq());
        helper.close();
    }
}
