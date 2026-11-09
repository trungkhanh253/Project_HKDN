"""Kiểm tra DB THẬT (theo migration của nhóm Server) trên DB test.

Quy ước kết quả:
- passed  : đúng với DB hiện tại (dùng để phát hiện hồi quy)
- xfailed : chỗ DB hiện tại KHÁC schema.md; chờ Lead chốt dùng bên nào
            (nếu được sửa đúng, test sẽ báo XPASS)
"""
import psycopg2
import psycopg2.errors as pgerr
import pytest

pytestmark = pytest.mark.db

TABLES = ["admin", "student", "subject", "enrollment",
          "checkin_history", "email_recipient"]


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
            "WHERE table_schema='public' AND table_name=%s", (table,))
        return {r[0]: {"nullable": r[1], "default": r[2]} for r in cur.fetchall()}


def _vec(*idx_values, dim=192):
    v = [0.0] * dim
    for i, x in idx_values:
        v[i] = x
    return "[" + ",".join(str(x) for x in v) + "]"


def _student(cur, sid="T1", seq=1, emb=None):
    cur.execute(
        "INSERT INTO student (student_id, full_name, class_name, face_embedding, "
        "seq, created_at, updated_at) VALUES (%s,'Test','CLS',%s::vector,%s,NOW(),NOW())",
        (sid, emb, seq))


def _subject(cur, code="SUB1", seq=1):
    cur.execute(
        "INSERT INTO subject (subject_code, subject_name, credits, seq, created_at, updated_at) "
        "VALUES (%s,'Test',3,%s,NOW(),NOW())", (code, seq))


def _enroll(cur, sid="T1", code="SUB1", seq=1):
    cur.execute(
        "INSERT INTO enrollment (student_id, subject_code, seq, created_at, updated_at) "
        "VALUES (%s,%s,%s,NOW(),NOW())", (sid, code, seq))


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
    for c in ("seq", "created_at", "updated_at", "deleted_at"):
        assert c in cols, f"{table} thiếu cột {c}"
    assert cols["seq"]["nullable"] == "NO"
    assert cols["updated_at"]["nullable"] == "NO"
    assert cols["deleted_at"]["nullable"] == "YES"  # NULL = chưa xóa mềm


@pytest.mark.parametrize("table", TABLES)
def test_seq_is_indexed(db, table):
    """sync/pull lọc theo seq nên phải có index."""
    assert _one(db, "SELECT 1 FROM pg_indexes WHERE tablename=%s "
                    "AND indexdef LIKE '%%(seq)%%'", (table,))


@pytest.mark.parametrize("table", TABLES)
def test_seq_has_no_default_so_app_must_assign(db, table):
    """Ghi nhận hiện trạng: seq không tự tăng, code ứng dụng phải gán."""
    assert _columns(db, table)["seq"]["default"] is None


# ---------- pgvector ----------
def test_face_embedding_is_vector_192(db):
    typ = _one(db, "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                   "WHERE a.attrelid='student'::regclass AND a.attname='face_embedding'")[0]
    assert typ == "vector(192)"


def test_wrong_vector_dimension_rejected(db):
    with pytest.raises(pgerr.DataException):  # lỗi sai chiều của pgvector
        with db.cursor() as cur:
            _student(cur, emb=_vec((0, 1.0), dim=191))


def test_vector_similarity_search_returns_nearest(db):
    with db.cursor() as cur:
        _student(cur, "NEAR", 1, _vec((0, 1.0)))
        _student(cur, "FAR", 2, _vec((1, 1.0)))
        cur.execute("SELECT student_id FROM student "
                    "WHERE face_embedding IS NOT NULL "
                    "ORDER BY face_embedding <=> %s::vector LIMIT 1", (_vec((0, 1.0)),))
        assert cur.fetchone()[0] == "NEAR"


# ---------- ràng buộc ----------
def test_student_primary_key_unique(db):
    with db.cursor() as cur:
        _student(cur, "DUP")
    with pytest.raises(pgerr.UniqueViolation):
        with db.cursor() as cur:
            _student(cur, "DUP", seq=2)


def test_admin_username_unique(db):
    sql = ("INSERT INTO admin (id, username, password_hash, full_name, seq, created_at, updated_at) "
           "VALUES (%s,'same_user','x','A',%s,NOW(),NOW())")
    with db.cursor() as cur:
        cur.execute(sql, ("a1", 1))
    with pytest.raises(pgerr.UniqueViolation):
        with db.cursor() as cur:
            cur.execute(sql, ("a2", 2))


def test_enrollment_requires_existing_student_and_subject(db):
    with pytest.raises(pgerr.ForeignKeyViolation):
        with db.cursor() as cur:
            _enroll(cur, "NO_SUCH", "NO_SUCH")


def test_checkin_requires_existing_student_and_subject(db):
    with pytest.raises(pgerr.ForeignKeyViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO checkin_history (id, student_id, subject_code, checkin_time, "
                "status, seq, created_at, updated_at) "
                "VALUES ('c1','NO_SUCH','NO_SUCH',NOW(),'present',1,NOW(),NOW())")


def test_insert_without_seq_is_rejected(db):
    with pytest.raises(pgerr.NotNullViolation):
        with db.cursor() as cur:
            cur.execute("INSERT INTO subject (subject_code, subject_name, credits, "
                        "created_at, updated_at) VALUES ('NOSEQ','T',3,NOW(),NOW())")


# ---------- chỗ DB KHÁC schema.md / có rủi ro (xfail = đã ghi nhận, chờ chốt) ----------
@pytest.mark.xfail(strict=False,
                   reason="schema.md yêu cầu cột uuid cho đồng bộ; DB thật chưa có (dùng id/khóa tự nhiên)")
@pytest.mark.parametrize("table", TABLES)
def test_table_has_uuid_column(db, table):
    assert "uuid" in _columns(db, table)


@pytest.mark.xfail(strict=False,
                   reason="schema.md: seq là BIGSERIAL tự tăng; DB thật không có default")
@pytest.mark.parametrize("table", TABLES)
def test_seq_auto_assigned(db, table):
    assert _columns(db, table)["seq"]["default"] is not None


@pytest.mark.xfail(strict=False,
                   reason="Không có trigger: UPDATE không tự tăng seq; sync/pull sẽ bỏ sót nếu code không gán")
def test_seq_bumps_on_update(db):
    with db.cursor() as cur:
        _student(cur, "U1", seq=1)
        cur.execute("UPDATE student SET full_name='Doi Ten' WHERE student_id='U1' RETURNING seq")
        assert cur.fetchone()[0] > 1


@pytest.mark.xfail(strict=False,
                   reason="enrollment chưa có UNIQUE(student_id, subject_code): có thể ghi danh trùng")
def test_enrollment_rejects_duplicate_pair(db):
    with db.cursor() as cur:
        _student(cur, "E1")
        _subject(cur, "ESUB")
        _enroll(cur, "E1", "ESUB", seq=1)
    with pytest.raises(pgerr.UniqueViolation):
        with db.cursor() as cur:
            _enroll(cur, "E1", "ESUB", seq=2)
