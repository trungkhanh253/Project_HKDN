--MÃ NGUỒN SQL DDL (POSTGRESQL SCRIPT)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

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
    seq BIGSERIAL UNIQUE NOT NULL
);

CREATE TABLE subjects (
    subject_id VARCHAR(255) PRIMARY KEY,
    subject_name VARCHAR(255) NOT NULL,
    time_slot VARCHAR(255),
    created_by VARCHAR(255) REFERENCES admins(admin_id) ON DELETE SET NULL,
    instructor_id VARCHAR(255) REFERENCES admins(admin_id) ON DELETE SET NULL,
    subject_status VARCHAR(50) NOT NULL DEFAULT 'UNASSIGNED',
    created_at VARCHAR(50),
    semester_start_date VARCHAR(50),
    semester_end_date VARCHAR(50),
    -- Cột đồng bộ hệ thống
    uuid VARCHAR(255) UNIQUE NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    seq BIGSERIAL UNIQUE NOT NULL
);

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
    seq BIGSERIAL UNIQUE NOT NULL
);

CREATE TABLE enrollments (
    student_id VARCHAR(255) REFERENCES students(student_id) ON DELETE CASCADE,
    subject_id VARCHAR(255) REFERENCES subjects(subject_id) ON DELETE CASCADE,
    enrollment_status VARCHAR(50),
    PRIMARY KEY (student_id, subject_id),
    -- Cột đồng bộ hệ thống
    uuid VARCHAR(255) UNIQUE NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    seq BIGSERIAL UNIQUE NOT NULL
);

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
    seq BIGSERIAL UNIQUE NOT NULL
);

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
    seq BIGSERIAL UNIQUE NOT NULL
);
