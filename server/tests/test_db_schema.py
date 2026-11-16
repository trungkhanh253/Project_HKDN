"""Kiểm tra DB chuẩn theo docs/schema.md trên DB test.

6 bảng chuẩn: admin, students, subjects, enrollments, checkin_history, email_recipients
Cơ chế đồng bộ:
- Tất cả các bảng đều có cột: uuid, updated_at, deleted_at, seq
- seq dùng chung 1 sequence toàn cục (global_sync_seq) + trigger tự động tăng khi INSERT và UPDATE
"""
import uuid
import psycopg2
import psycopg2.errors as pgerr
import pytest

pytestmark = pytest.mark.db

TABLES = [
    "admin",
    "students",
    "subjects",
    "enrollments",
    "checkin_history",
    "email_recipients",
]


# ---------- helper ----------
def _one(db, sql, params=None):
    with db.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _columns(db, table):
    with db.cursor() as cur:
        cur.execute(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s",
            (table,),
        )
        return {r[0]: {"nullable": r[1], "default": r[2]} for r in cur.fetchall()}


def _vec(*idx_values, dim=192):
    v = [0.0] * dim
    for i, x in idx_values:
        v[i] = x
    return "[" + ",".join(str(x) for x in v) + "]"


def _student(cur, sid="T1", emb=None):
    cur.execute(
        "INSERT INTO students (student_id, full_name, email, phone, face_embedding, uuid, updated_at) "
        "VALUES (%s, 'Test', 'test@edu.vn', '0900000000', %s::vector, %s, NOW())",
        (sid, emb, str(uuid.uuid4())),
    )


def _subject(cur, code="SUB1"):
    cur.execute(
        "INSERT INTO subjects (subject_id, subject_name, subject_status, uuid, updated_at) "
        "VALUES (%s, 'Test Subject', 'UNASSIGNED', %s, NOW())",
        (code, str(uuid.uuid4())),
    )


def _enroll(cur, sid="T1", code="SUB1"):
    cur.execute(
        "INSERT INTO enrollments (student_id, subject_id, enrollment_status, uuid, updated_at) "
        "VALUES (%s, %s, 'Enrolled', %s, NOW())",
        (sid, code, str(uuid.uuid4())),
    )


# ---------- hạ tầng ----------
def test_pgvector_extension_installed(db):
    assert _one(db, "SELECT 1 FROM pg_extension WHERE extname='vector'")


@pytest.mark.parametrize("table", TABLES)
def test_table_exists(db, table):
    assert _one(db, "SELECT to_regclass(%s)", (f"public.{table}",))[0] is not None


# ---------- metadata đồng bộ ----------
@pytest.mark.parametrize("table", TABLES)
def test_sync_metadata_columns(db, table):
    cols = _columns(db, table)
    for c in ("uuid", "seq", "updated_at", "deleted_at"):
        assert c in cols, f"{table} thiếu cột {c}"
    assert cols["uuid"]["nullable"] == "NO"
    assert cols["seq"]["nullable"] == "NO"
    assert cols["updated_at"]["nullable"] == "NO"
    assert cols["deleted_at"]["nullable"] == "YES"  # NULL = chưa xóa mềm


@pytest.mark.parametrize("table", TABLES)
def test_table_has_uuid_column(db, table):
    assert "uuid" in _columns(db, table)


@pytest.mark.parametrize("table", TABLES)
def test_seq_is_indexed(db, table):
    """sync/pull lọc theo seq nên phải có index."""
    assert _one(
        db,
        "SELECT 1 FROM pg_indexes WHERE tablename=%s AND indexdef LIKE '%%(seq)%%'",
        (table,),
    )


@pytest.mark.parametrize("table", TABLES)
def test_seq_auto_assigned(db, table):
    """seq có default từ sequence chung global_sync_seq."""
    assert _columns(db, table)["seq"]["default"] is not None


def test_seq_bumps_on_update(db):
    """Trigger tự động tăng seq khi UPDATE (bao gồm sửa thông tin hoặc xóa mềm)."""
    with db.cursor() as cur:
        _student(cur, "U1")
        cur.execute("SELECT seq FROM students WHERE student_id='U1'")
        initial_seq = cur.fetchone()[0]

        cur.execute(
            "UPDATE students SET full_name='Doi Ten' WHERE student_id='U1' RETURNING seq"
        )
        updated_seq = cur.fetchone()[0]
        assert updated_seq > initial_seq


def test_global_sequence_shared_across_tables(db):
    """Sequence dùng chung tăng liên tiếp giữa các bảng khác nhau."""
    with db.cursor() as cur:
        _student(cur, "S_SEQ")
        cur.execute("SELECT seq FROM students WHERE student_id='S_SEQ'")
        s_seq = cur.fetchone()[0]

        _subject(cur, "SUB_SEQ")
        cur.execute("SELECT seq FROM subjects WHERE subject_id='SUB_SEQ'")
        sub_seq = cur.fetchone()[0]

        assert sub_seq > s_seq


# ---------- pgvector ----------
def test_face_embedding_is_vector_192(db):
    typ = _one(
        db,
        "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
        "WHERE a.attrelid='students'::regclass AND a.attname='face_embedding'",
    )[0]
    assert typ == "vector(192)"


def test_wrong_vector_dimension_rejected(db):
    with pytest.raises(pgerr.DataException):  # lỗi sai chiều của pgvector
        with db.cursor() as cur:
            _student(cur, emb=_vec((0, 1.0), dim=191))


def test_vector_similarity_search_returns_nearest(db):
    with db.cursor() as cur:
        _student(cur, "NEAR", _vec((0, 1.0)))
        _student(cur, "FAR", _vec((1, 1.0)))
        cur.execute(
            "SELECT student_id FROM students "
            "WHERE face_embedding IS NOT NULL "
            "ORDER BY face_embedding <=> %s::vector LIMIT 1",
            (_vec((0, 1.0)),),
        )
        assert cur.fetchone()[0] == "NEAR"


# ---------- ràng buộc ----------
def test_student_primary_key_unique(db):
    with db.cursor() as cur:
        _student(cur, "DUP")
    with pytest.raises(pgerr.UniqueViolation):
        with db.cursor() as cur:
            _student(cur, "DUP")


def test_admin_email_unique(db):
    sql = (
        "INSERT INTO admin (admin_id, email, password, full_name, role, uuid, updated_at) "
        "VALUES (%s, 'same@edu.vn', 'x', 'Admin A', 'ADMIN', %s, NOW())"
    )
    with db.cursor() as cur:
        cur.execute(sql, ("a1", str(uuid.uuid4())))
    with pytest.raises(pgerr.UniqueViolation):
        with db.cursor() as cur:
            cur.execute(sql, ("a2", str(uuid.uuid4())))


def test_enrollment_requires_existing_student_and_subject(db):
    with pytest.raises(pgerr.ForeignKeyViolation):
        with db.cursor() as cur:
            _enroll(cur, "NO_SUCH", "NO_SUCH")


def test_enrollment_rejects_duplicate_pair(db):
    with db.cursor() as cur:
        _student(cur, "E1")
        _subject(cur, "ESUB")
        _enroll(cur, "E1", "ESUB")
    with pytest.raises(pgerr.UniqueViolation):
        with db.cursor() as cur:
            _enroll(cur, "E1", "ESUB")


def test_checkin_requires_existing_student_and_subject(db):
    with pytest.raises(pgerr.ForeignKeyViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO checkin_history (student_id, subject_id, checkin_time, "
                "checkin_date, uuid, updated_at) "
                "VALUES ('NO_SUCH', 'NO_SUCH', '08:00:00', '2026-11-09', %s, NOW())",
                (str(uuid.uuid4()),),
            )
