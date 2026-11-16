-- MÃ NGUỒN SQL DDL (POSTGRESQL SCRIPT)

CREATE EXTENSION IF NOT EXISTS vector;

-- Sequence dùng chung cho toàn bộ 6 bảng để đồng bộ (sync/pull & sync/push)
CREATE SEQUENCE IF NOT EXISTS global_sync_seq START 1;

-- Trigger function tự động tăng seq và cập nhật updated_at khi INSERT hoặc UPDATE
CREATE OR REPLACE FUNCTION bump_sync_metadata()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.seq IS NULL THEN
            NEW.seq := nextval('global_sync_seq');
        ELSE
            PERFORM setval('global_sync_seq', GREATEST(NEW.seq, COALESCE((SELECT last_value FROM global_sync_seq WHERE is_called), 0)), true);
        END IF;
        IF NEW.updated_at IS NULL THEN
            NEW.updated_at := CURRENT_TIMESTAMP;
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        NEW.seq := nextval('global_sync_seq');
        IF NEW.seq <= OLD.seq THEN
            NEW.seq := OLD.seq + 1;
            PERFORM setval('global_sync_seq', NEW.seq, true);
        END IF;
        IF NEW.updated_at IS NULL OR NEW.updated_at = OLD.updated_at THEN
            NEW.updated_at := CURRENT_TIMESTAMP;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE admin (
    admin_id VARCHAR(255) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    date_of_birth VARCHAR(50),
    phone VARCHAR(50),
    gender VARCHAR(50),
    photo_path TEXT,
    description TEXT,
    role VARCHAR(50) NOT NULL DEFAULT 'ADMIN',
    admin_code VARCHAR(100),
    reset_token VARCHAR(255),
    expire_at BIGINT,
    is_first_login INT DEFAULT 1,
    has_iris INT DEFAULT 0,
    face_embedding VECTOR(192),
    -- Cột đồng bộ hệ thống
    uuid VARCHAR(255) UNIQUE NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    seq BIGINT UNIQUE NOT NULL DEFAULT nextval('global_sync_seq')
);
CREATE INDEX ix_admin_seq ON admin (seq);
CREATE TRIGGER trg_admin_sync_metadata
BEFORE INSERT OR UPDATE ON admin
FOR EACH ROW EXECUTE FUNCTION bump_sync_metadata();

CREATE TABLE subjects (
    subject_id VARCHAR(255) PRIMARY KEY,
    subject_name VARCHAR(255) NOT NULL,
    time_slot VARCHAR(255),
    created_by VARCHAR(255) REFERENCES admin(admin_id) ON DELETE SET NULL,
    instructor_id VARCHAR(255) REFERENCES admin(admin_id) ON DELETE SET NULL,
    subject_status VARCHAR(50) NOT NULL DEFAULT 'UNASSIGNED',
    created_at VARCHAR(50),
    semester_start_date VARCHAR(50),
    semester_end_date VARCHAR(50),
    -- Cột đồng bộ hệ thống
    uuid VARCHAR(255) UNIQUE NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    seq BIGINT UNIQUE NOT NULL DEFAULT nextval('global_sync_seq')
);
CREATE INDEX ix_subjects_seq ON subjects (seq);
CREATE TRIGGER trg_subjects_sync_metadata
BEFORE INSERT OR UPDATE ON subjects
FOR EACH ROW EXECUTE FUNCTION bump_sync_metadata();

CREATE TABLE students (
    student_id VARCHAR(255) PRIMARY KEY,
    full_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    photo_path TEXT,
    checkin_password VARCHAR(255),
    face_embedding VECTOR(192),
    -- Cột đồng bộ hệ thống
    uuid VARCHAR(255) UNIQUE NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    seq BIGINT UNIQUE NOT NULL DEFAULT nextval('global_sync_seq')
);
CREATE INDEX ix_students_seq ON students (seq);
CREATE TRIGGER trg_students_sync_metadata
BEFORE INSERT OR UPDATE ON students
FOR EACH ROW EXECUTE FUNCTION bump_sync_metadata();

CREATE TABLE enrollments (
    student_id VARCHAR(255) REFERENCES students(student_id) ON DELETE CASCADE,
    subject_id VARCHAR(255) REFERENCES subjects(subject_id) ON DELETE CASCADE,
    enrollment_status VARCHAR(50),
    PRIMARY KEY (student_id, subject_id),
    -- Cột đồng bộ hệ thống
    uuid VARCHAR(255) UNIQUE NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    seq BIGINT UNIQUE NOT NULL DEFAULT nextval('global_sync_seq')
);
CREATE INDEX ix_enrollments_seq ON enrollments (seq);
CREATE TRIGGER trg_enrollments_sync_metadata
BEFORE INSERT OR UPDATE ON enrollments
FOR EACH ROW EXECUTE FUNCTION bump_sync_metadata();

CREATE TABLE checkin_history (
    checkin_id SERIAL PRIMARY KEY,
    student_id VARCHAR(255) REFERENCES students(student_id) ON DELETE CASCADE,
    subject_id VARCHAR(255) REFERENCES subjects(subject_id) ON DELETE CASCADE,
    checkin_time VARCHAR(50),
    checkin_date VARCHAR(50),
    -- Cột đồng bộ hệ thống
    uuid VARCHAR(255) UNIQUE NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    seq BIGINT UNIQUE NOT NULL DEFAULT nextval('global_sync_seq')
);
CREATE INDEX ix_checkin_history_seq ON checkin_history (seq);
CREATE TRIGGER trg_checkin_history_sync_metadata
BEFORE INSERT OR UPDATE ON checkin_history
FOR EACH ROW EXECUTE FUNCTION bump_sync_metadata();

CREATE TABLE email_recipients (
    email_id SERIAL PRIMARY KEY,
    subject_id VARCHAR(255) NOT NULL REFERENCES subjects(subject_id) ON DELETE CASCADE,
    email_address VARCHAR(255) NOT NULL,
    recipient_name VARCHAR(255),
    added_date VARCHAR(50),
    is_selected BOOLEAN DEFAULT TRUE,
    CONSTRAINT unique_subject_email UNIQUE (subject_id, email_address),
    -- Cột đồng bộ hệ thống
    uuid VARCHAR(255) UNIQUE NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    seq BIGINT UNIQUE NOT NULL DEFAULT nextval('global_sync_seq')
);
CREATE INDEX ix_email_recipients_seq ON email_recipients (seq);
CREATE TRIGGER trg_email_recipients_sync_metadata
BEFORE INSERT OR UPDATE ON email_recipients
FOR EACH ROW EXECUTE FUNCTION bump_sync_metadata();
