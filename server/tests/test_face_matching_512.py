"""
Bộ kiểm thử tự động cho TV4 - Module xác thực & nhận diện khuôn mặt 512 chiều (Tasks 10, 11, 12).

Kiểm tra toàn diện:
1. Đồng nhất toán học (Cosine Similarity, L2-Normalize, Batch Cosine Similarity, Threshold 0.40) với Nhóm 3 (Face-service).
2. Bộ nhận dữ liệu đa năng `ensure_vector_512` (list, ndarray, JSON string, bytes BLOB, dict `/v1/embeddings`).
3. Xác thực 1:1 (`verify_student_face_512`): đúng người (MATCHED), sai người (FACE_MISMATCH), biên ngưỡng (0.399 vs 0.400).
4. Nhận diện 1:N (`identify_student_face_512`): tìm đúng sinh viên trong lớp, chống nhập nhằng (AMBIGUOUS_MATCH), ẩn danh tính khi dưới ngưỡng.
5. Xử lý thiếu vector 512 (`MISSING_VECTOR_512`) ở cả 1:1 và 1:N.
6. Chặn vector/ảnh không hợp lệ (`INVALID_IMAGE_OR_VECTOR`): None, vector 192 chiều cũ, NaN/Inf, zero-vector, nhiều mặt/không có mặt từ Face-service.
7. Lọc xóa mềm (`Student.deleted_at` & `Enrollment.deleted_at`) và phân quyền giảng viên (`FORBIDDEN` vs `SUPER_ADMIN`).
8. Bảo mật Zero-Biometric Logging: Không ghi mảng số thực của vector sinh trắc vào log.
"""
from __future__ import annotations

import json
import logging
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest


def _ensure_stub_app_modules_if_needed():
    """
    Cho phép chạy bộ unit test độc lập ngay cả trên môi trường Python local chưa cài
    đầy đủ pgvector/flask_sqlalchemy (hoặc chạy trực tiếp trong container Docker).
    """
    try:
        import app.models  # noqa: F401
        return
    except Exception:
        pass

    if "flask" not in sys.modules:
        flask_stub = types.ModuleType("flask")
        flask_stub.g = SimpleNamespace()
        flask_stub.has_app_context = lambda: False
        flask_stub.has_request_context = lambda: False
        flask_stub.request = SimpleNamespace(headers={}, form={})
        sys.modules["flask"] = flask_stub

    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = ["app"]
    app_pkg.db = MagicMock()
    sys.modules["app"] = app_pkg

    class _FakeCol:
        def __init__(self, name: str):
            self.name = name

        def __eq__(self, other):
            return ("eq", self.name, other)

        def is_(self, other):
            return ("is", self.name, other)

        def asc(self):
            return ("asc", self.name)

    models_mod = types.ModuleType("app.models")

    class FakeSubject:
        subject_id = _FakeCol("subject_id")
        deleted_at = _FakeCol("deleted_at")
        query = MagicMock()

    class FakeStudent:
        student_id = _FakeCol("student_id")
        deleted_at = _FakeCol("deleted_at")
        query = MagicMock()

    class FakeEnrollment:
        student_id = _FakeCol("student_id")
        subject_id = _FakeCol("subject_id")
        deleted_at = _FakeCol("deleted_at")
        query = MagicMock()

    models_mod.Subject = FakeSubject
    models_mod.Student = FakeStudent
    models_mod.Enrollment = FakeEnrollment
    sys.modules["app.models"] = models_mod


_ensure_stub_app_modules_if_needed()

from app.services import face_matching_service as fms  # noqa: E402
from app.services.face_matching_service import (  # noqa: E402
    DEFAULT_MATCH_THRESHOLD_512,
    EMBEDDING_DIM_512,
    STATUS_AMBIGUOUS_MATCH,
    STATUS_FACE_MISMATCH,
    STATUS_FORBIDDEN,
    STATUS_INVALID_IMAGE_OR_VECTOR,
    STATUS_MATCHED,
    STATUS_MISSING_VECTOR_512,
    STATUS_NOT_ENROLLED,
    STATUS_STUDENT_NOT_FOUND,
    STATUS_SUBJECT_NOT_FOUND,
    InvalidFaceVectorError,
    batch_cosine_similarity,
    cosine_distance,
    cosine_similarity,
    ensure_vector_512,
    identify_student_face_512,
    is_match,
    l2_normalize,
    match_face_for_attendance,
    verify_student_face_512,
)


def _make_basis_vector(index: int, scale: float = 1.0) -> np.ndarray:
    """Tạo vector 512 chiều trực giao tại vị trí `index`."""
    vec = np.zeros((EMBEDDING_DIM_512,), dtype=np.float32)
    vec[index % EMBEDDING_DIM_512] = float(scale)
    return vec


def _make_vector_with_similarity(base_vec: np.ndarray, target_sim: float, orth_index: int = 1) -> np.ndarray:
    """
    Tạo vector 512 chiều có Cosine Similarity chính xác bằng `target_sim` so với `base_vec`.
    v = target_sim * u + sqrt(1 - target_sim^2) * u_orth
    """
    u = l2_normalize(base_vec)
    orth = _make_basis_vector(orth_index)
    # Đảm bảo orth vuông góc với u
    orth = orth - float(np.dot(orth, u)) * u
    orth = l2_normalize(orth)
    sim = float(np.clip(target_sim, -1.0, 1.0))
    sin_val = float(np.sqrt(max(0.0, 1.0 - sim * sim)))
    return (sim * u + sin_val * orth).astype(np.float32)


@pytest.fixture
def mock_db_env(monkeypatch):
    """
    Thiết lập dữ liệu giả lập trong bộ nhớ cho Subject, Student, Enrollment
    để kiểm thử toàn bộ luồng nghiệp vụ 1:1 và 1:N của TV4.
    """
    subjects = {}
    students = {}
    enrollments = []

    def add_subject(subject_id: str, instructor_id: str = "LEC_01", deleted_at=None):
        subj = SimpleNamespace(
            subject_id=subject_id,
            subject_name=f"Môn {subject_id}",
            instructor_id=instructor_id,
            deleted_at=deleted_at,
        )
        subjects[subject_id] = subj
        return subj

    def add_student(student_id: str, vec_512=None, full_name: str = None, deleted_at=None):
        stu = SimpleNamespace(
            student_id=student_id,
            full_name=full_name or f"Sinh viên {student_id}",
            face_embedding_512=vec_512,
            face_embedding=None,
            deleted_at=deleted_at,
        )
        students[student_id] = stu
        return stu

    def enroll(student_id: str, subject_id: str, deleted_at=None):
        enr = SimpleNamespace(
            student_id=student_id,
            subject_id=subject_id,
            deleted_at=deleted_at,
        )
        enrollments.append(enr)
        return enr

    def subject_filter_by(**kw):
        q = MagicMock()
        sid = kw.get("subject_id")
        s = subjects.get(sid)
        if s is not None and ("deleted_at" not in kw or s.deleted_at == kw["deleted_at"]):
            q.first.return_value = s
        else:
            q.first.return_value = None
        return q

    def student_filter_by(**kw):
        q = MagicMock()
        sid = kw.get("student_id")
        s = students.get(sid)
        if s is not None and ("deleted_at" not in kw or s.deleted_at == kw["deleted_at"]):
            q.first.return_value = s
        else:
            q.first.return_value = None
        return q

    def enrollment_filter_by(**kw):
        q = MagicMock()
        sid = kw.get("student_id")
        sub_id = kw.get("subject_id")
        found = None
        for e in enrollments:
            if e.student_id == sid and e.subject_id == sub_id:
                if "deleted_at" not in kw or e.deleted_at == kw["deleted_at"]:
                    found = e
                    break
        q.first.return_value = found
        return q

    monkeypatch.setattr(
        fms,
        "Subject",
        SimpleNamespace(query=SimpleNamespace(filter_by=subject_filter_by)),
    )
    monkeypatch.setattr(
        fms,
        "Student",
        SimpleNamespace(
            student_id=MagicMock(asc=lambda: "student_id_asc"),
            deleted_at=MagicMock(is_=lambda x: ("is", x)),
            query=SimpleNamespace(filter_by=student_filter_by),
        ),
    )
    monkeypatch.setattr(
        fms,
        "Enrollment",
        SimpleNamespace(
            student_id=MagicMock(),
            subject_id=MagicMock(),
            deleted_at=MagicMock(is_=lambda x: ("is", x)),
            query=SimpleNamespace(filter_by=enrollment_filter_by),
        ),
    )

    # Mock db.session.query(Student).join(Enrollment, ...).filter(...).order_by(...).all()
    current_subject_holder = {"subject_id": None}
    orig_verify = fms._verify_subject_and_permission

    def wrapped_verify(subject_id: str, admin=None):
        current_subject_holder["subject_id"] = subject_id
        return orig_verify(subject_id, admin=admin)

    monkeypatch.setattr(fms, "_verify_subject_and_permission", wrapped_verify)

    def fake_session_query(model):
        q = MagicMock()
        q.join.return_value = q
        q.filter.return_value = q
        q.order_by.return_value = q

        def all_fn():
            sub_id = current_subject_holder["subject_id"]
            res = []
            for e in enrollments:
                if e.subject_id == sub_id and e.deleted_at is None:
                    stu = students.get(e.student_id)
                    if stu is not None and stu.deleted_at is None:
                        res.append(stu)
            res.sort(key=lambda x: x.student_id)
            return res

        q.all.side_effect = all_fn
        return q

    monkeypatch.setattr(
        fms,
        "db",
        SimpleNamespace(session=SimpleNamespace(query=fake_session_query)),
    )

    return SimpleNamespace(
        add_subject=add_subject,
        add_student=add_student,
        enroll=enroll,
        subjects=subjects,
        students=students,
        enrollments=enrollments,
    )


# =====================================================================
# 1. TEST TOÁN HỌC & BỘ CHUẨN HÓA ĐẦU VÀO (TASK 10 & TASK 11)
# =====================================================================

def test_math_consistency_and_default_threshold():
    """Kiểm tra công thức Cosine Similarity, Distance, Batch và ngưỡng mặc định 0.40."""
    assert DEFAULT_MATCH_THRESHOLD_512 == pytest.approx(0.40)

    v1 = _make_basis_vector(0, scale=3.5)
    v2 = _make_vector_with_similarity(v1, 0.668, orth_index=1)  # Mean genuine của Nhóm 3
    v3 = _make_vector_with_similarity(v1, 0.262, orth_index=2)  # Max impostor của Nhóm 3

    sim_genuine = cosine_similarity(v1, v2)
    sim_impostor = cosine_similarity(v1, v3)

    assert sim_genuine == pytest.approx(0.668, abs=1e-5)
    assert cosine_distance(v1, v2) == pytest.approx(1.0 - 0.668, abs=1e-5)
    assert is_match(sim_genuine) is True

    assert sim_impostor == pytest.approx(0.262, abs=1e-5)
    assert is_match(sim_impostor) is False

    batch_sims = batch_cosine_similarity(v1, np.vstack([v2, v3]))
    assert batch_sims.shape == (2,)
    assert batch_sims[0] == pytest.approx(0.668, abs=1e-5)
    assert batch_sims[1] == pytest.approx(0.262, abs=1e-5)


def test_ensure_vector_512_supports_multiple_formats():
    """Hỗ trợ list, ndarray, chuỗi JSON, bytes BLOB và dict response từ Face-service (/v1/embeddings)."""
    raw_vec = _make_basis_vector(5, scale=2.0)

    # 1. Từ list[float]
    assert np.allclose(ensure_vector_512(raw_vec.tolist()), raw_vec)

    # 2. Từ chuỗi JSON (ví dụ đọc từ text/mock DB)
    json_str = json.dumps(raw_vec.tolist())
    assert np.allclose(ensure_vector_512(json_str), raw_vec)

    # 3. Từ bytes BLOB (2048 bytes little-endian float32)
    blob = raw_vec.astype("<f4").tobytes()
    assert np.allclose(ensure_vector_512(blob), raw_vec)

    # 4. Từ dict response của POST /v1/embeddings (Nhóm 3 / TV2 FaceServiceClient)
    face_service_resp = {
        "dim": 512,
        "embedding": raw_vec.tolist(),
        "dim_192": 192,
        "embedding_192": [0.1] * 192,
        "detector": "retinaface",
        "face": {"bbox": [10, 10, 100, 100], "det_score": 0.998, "face_count": 1},
    }
    assert np.allclose(ensure_vector_512(face_service_resp), raw_vec)


@pytest.mark.parametrize(
    "bad_input",
    [
        None,
        [],
        [0.1] * 192,  # Vector 192 chiều MobileFaceNet cũ truyền nhầm
        [0.1] * 511,
        [0.1] * 513,
        [0.0] * 512,  # Zero vector (norm = 0)
        [float("nan")] + [0.1] * 511,
        [float("inf")] + [0.1] * 511,
        [True] * 512,  # Boolean array
        "",
        "not-a-json",
        {"detail": "Không phát hiện khuôn mặt trong ảnh."},  # Lỗi 422 từ Face-service
        {"success": False, "code": "NO_FACE"},
        {"dim": 512, "embedding": [0.1] * 512, "face": {"face_count": 2}},  # Nhiều mặt trong ảnh
    ],
)
def test_ensure_vector_512_rejects_invalid_inputs(bad_input):
    """Mọi dữ liệu ảnh/vector lỗi đều phải bị chặn với InvalidFaceVectorError."""
    with pytest.raises(InvalidFaceVectorError):
        ensure_vector_512(bad_input)


# =====================================================================
# 2. TEST XÁC THỰC 1:1 (VERIFY_STUDENT_FACE_512)
# =====================================================================

def test_1to1_genuine_and_impostor_and_threshold_boundary(mock_db_env):
    """Kiểm thử 1:1 đúng người, sai người và sát biên ngưỡng 0.399 vs 0.400."""
    lec = SimpleNamespace(admin_id="LEC_01", role="ADMIN")
    base_vec = _make_basis_vector(0)

    mock_db_env.add_subject("IT001", instructor_id="LEC_01")
    mock_db_env.add_student("SV001", vec_512=base_vec)
    mock_db_env.enroll("SV001", "IT001")

    # 1. Đúng người (similarity = 0.72 >= 0.40) -> MATCHED
    query_ok = _make_vector_with_similarity(base_vec, 0.72, orth_index=1)
    res_ok = match_face_for_attendance(query_ok, subject_id="IT001", student_id="SV001", admin=lec)
    assert res_ok.matched is True
    assert res_ok.status == STATUS_MATCHED
    assert res_ok.mode == "1:1"
    assert res_ok.student_id == "SV001"
    assert res_ok.http_status == 200
    assert res_ok.similarity == pytest.approx(0.72, abs=1e-4)

    # 2. Sai người (similarity = 0.21 < 0.40) -> FACE_MISMATCH
    query_bad = _make_vector_with_similarity(base_vec, 0.21, orth_index=2)
    res_bad = match_face_for_attendance(query_bad, subject_id="IT001", student_id="SV001", admin=lec)
    assert res_bad.matched is False
    assert res_bad.status == STATUS_FACE_MISMATCH
    assert res_bad.http_status == 422

    # 3. Sát biên ngưỡng: 0.399 -> FACE_MISMATCH, 0.401 -> MATCHED
    q_399 = _make_vector_with_similarity(base_vec, 0.399, orth_index=3)
    q_401 = _make_vector_with_similarity(base_vec, 0.401, orth_index=4)
    assert verify_student_face_512(q_399, "SV001", "IT001", admin=lec).matched is False
    assert verify_student_face_512(q_401, "SV001", "IT001", admin=lec).matched is True


def test_1to1_missing_vector_and_invalid_input(mock_db_env):
    """Kiểm thử sinh viên chưa có vector 512 và trường hợp truyền ảnh/vector không hợp lệ."""
    lec = SimpleNamespace(admin_id="LEC_01", role="ADMIN")
    mock_db_env.add_subject("IT001", instructor_id="LEC_01")
    mock_db_env.add_student("SV_NO_VEC", vec_512=None)
    mock_db_env.enroll("SV_NO_VEC", "IT001")

    valid_query = _make_basis_vector(0)

    # Sinh viên chưa có face_embedding_512 -> MISSING_VECTOR_512
    res_missing = match_face_for_attendance(valid_query, subject_id="IT001", student_id="SV_NO_VEC", admin=lec)
    assert res_missing.matched is False
    assert res_missing.status == STATUS_MISSING_VECTOR_512
    assert res_missing.http_status == 422

    # Truyền vector 192 chiều hoặc dict báo lỗi ảnh không có khuôn mặt -> INVALID_IMAGE_OR_VECTOR
    res_inv = match_face_for_attendance([0.1] * 192, subject_id="IT001", student_id="SV_NO_VEC", admin=lec)
    assert res_inv.matched is False
    assert res_inv.status == STATUS_INVALID_IMAGE_OR_VECTOR
    assert res_inv.http_status == 422


# =====================================================================
# 3. TEST NHẬN DIỆN 1:N TRONG PHẠM VI MÔN HỌC & PHÂN QUYỀN
# =====================================================================

def test_1toN_identify_and_ambiguous_tie_break(mock_db_env):
    """Kiểm thử nhận diện 1:N trong lớp học, ẩn student_id khi không khớp, và phát hiện AMBIGUOUS_MATCH."""
    lec = SimpleNamespace(admin_id="LEC_01", role="ADMIN")
    mock_db_env.add_subject("IT001", instructor_id="LEC_01")

    v_sv1 = _make_basis_vector(0)
    v_sv2 = _make_basis_vector(1)
    v_sv3 = _make_basis_vector(2)

    mock_db_env.add_student("SV001", vec_512=v_sv1)
    mock_db_env.add_student("SV002", vec_512=v_sv2)
    mock_db_env.add_student("SV003", vec_512=v_sv3)
    mock_db_env.enroll("SV001", "IT001")
    mock_db_env.enroll("SV002", "IT001")
    # Lưu ý: SV003 KHÔNG ghi danh vào môn IT001

    # 1. Query khớp rõ ràng với SV002 (sim = 0.85)
    q_sv2 = _make_vector_with_similarity(v_sv2, 0.85, orth_index=10)
    res_1n = match_face_for_attendance(q_sv2, subject_id="IT001", student_id=None, admin=lec)
    assert res_1n.matched is True
    assert res_1n.status == STATUS_MATCHED
    assert res_1n.mode == "1:N"
    assert res_1n.student_id == "SV002"

    # 2. Query khớp với SV003 (người ngoài lớp IT001) -> Trong lớp IT001 phải trả về FACE_MISMATCH và student_id=None
    res_outsider = match_face_for_attendance(v_sv3, subject_id="IT001", student_id=None, admin=lec)
    assert res_outsider.matched is False
    assert res_outsider.status == STATUS_FACE_MISMATCH
    assert res_outsider.student_id is None

    # 3. Hai sinh viên trong lớp có vector quá sát nhau cùng >= 0.40 (margin < 0.05) -> AMBIGUOUS_MATCH
    v_sv4 = _make_vector_with_similarity(v_sv1, 0.999, orth_index=20)
    mock_db_env.add_student("SV004", vec_512=v_sv4)
    mock_db_env.enroll("SV004", "IT001")

    res_amb = identify_student_face_512(v_sv1, subject_id="IT001", admin=lec, min_margin=0.05)
    assert res_amb.matched is False
    assert res_amb.status == STATUS_AMBIGUOUS_MATCH
    assert res_amb.student_id is None
    assert len(res_amb.candidates) == 2


def test_rbac_and_soft_deleted_records(mock_db_env):
    """Kiểm thử phân quyền giảng viên (403 FORBIDDEN) và loại bỏ sinh viên/ghi danh đã xóa mềm."""
    lec1 = SimpleNamespace(admin_id="LEC_01", role="ADMIN")
    lec2 = SimpleNamespace(admin_id="LEC_02", role="ADMIN")
    super_adm = SimpleNamespace(admin_id="ADM_ROOT", role="SUPER_ADMIN")

    v_sv1 = _make_basis_vector(0)
    mock_db_env.add_subject("IT001", instructor_id="LEC_01")
    mock_db_env.add_student("SV001", vec_512=v_sv1)
    enr = mock_db_env.enroll("SV001", "IT001")

    # 1. Giảng viên LEC_02 gọi môn của LEC_01 -> 403 FORBIDDEN
    res_forbidden = match_face_for_attendance(v_sv1, subject_id="IT001", student_id="SV001", admin=lec2)
    assert res_forbidden.matched is False
    assert res_forbidden.status == STATUS_FORBIDDEN
    assert res_forbidden.http_status == 403

    # 2. SUPER_ADMIN gọi môn của LEC_01 -> 200 MATCHED
    res_super = match_face_for_attendance(v_sv1, subject_id="IT001", student_id="SV001", admin=super_adm)
    assert res_super.matched is True
    assert res_super.status == STATUS_MATCHED

    # 3. Hủy ghi danh (xóa mềm Enrollment) -> 1:1 trả NOT_ENROLLED
    enr.deleted_at = "2026-11-27T00:00:00Z"
    res_unenrolled = match_face_for_attendance(v_sv1, subject_id="IT001", student_id="SV001", admin=lec1)
    assert res_unenrolled.matched is False
    assert res_unenrolled.status == STATUS_NOT_ENROLLED


def test_zero_biometric_logging(mock_db_env, caplog):
    """Đảm bảo tuyệt đối không có phần tử vector sinh trắc học nào bị ghi vào log."""
    caplog.set_level(logging.INFO, logger="face_matching_512")
    lec = SimpleNamespace(admin_id="LEC_01", role="ADMIN")

    secret_val = 0.7391824
    vec = np.zeros((EMBEDDING_DIM_512,), dtype=np.float32)
    vec[0] = secret_val
    vec[1] = 0.5123456

    mock_db_env.add_subject("IT001", instructor_id="LEC_01")
    mock_db_env.add_student("SV001", vec_512=vec)
    mock_db_env.enroll("SV001", "IT001")

    match_face_for_attendance(vec, subject_id="IT001", student_id="SV001", admin=lec)
    match_face_for_attendance([0.1] * 192, subject_id="IT001", student_id="SV001", admin=lec)

    logged_text = caplog.text
    assert "0.7391824" not in logged_text
    assert "0.5123456" not in logged_text


# =====================================================================
# 4. TEST ADAPTER FACEMATCHINGSERVICE TƯƠNG THÍCH 100% VỚI TV5 (TUYÊN)
# =====================================================================

def test_tv5_face_matching_service_adapter_compatibility():
    """Kiểm tra class FaceMatchingService tương thích hoàn toàn với POST /attendance/face của TV5."""
    from app.services.face_matching_service import (
        FaceMatchingService,
        FaceNotDetectedError,
        FaceServiceUnavailableError,
    )

    v_stu = _make_basis_vector(3)
    student = SimpleNamespace(student_id="SV_TV5", face_embedding_512=v_stu, face_embedding=None)
    sample_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00" + b"\x00" * 64

    # 1. Tích hợp với FaceServiceClient (TV2) trả về dict /v1/embeddings khớp người (sim = 0.68 >= 0.40)
    q_ok = _make_vector_with_similarity(v_stu, 0.68, orth_index=7)
    fake_client_ok = SimpleNamespace(
        extract_embedding=lambda img_bytes: {"dim": 512, "embedding": q_ok.tolist(), "face": {"face_count": 1}}
    )
    ok, score, msg = FaceMatchingService.verify_face(student, sample_jpeg, face_service_client=fake_client_ok)
    assert ok is True
    assert score == pytest.approx(0.68, abs=1e-3)

    # 2. Khác người (sim = 0.19 < 0.40) -> ok = False
    q_bad = _make_vector_with_similarity(v_stu, 0.19, orth_index=8)
    fake_client_bad = SimpleNamespace(
        extract_embedding=lambda img_bytes: {"dim": 512, "embedding": q_bad.tolist(), "face": {"face_count": 1}}
    )
    ok2, score2, _ = FaceMatchingService.verify_face(student, sample_jpeg, face_service_client=fake_client_bad)
    assert ok2 is False
    assert score2 == pytest.approx(0.19, abs=1e-3)

    # 3. Ảnh rác / không đúng định dạng JPEG/PNG/WebP -> FaceNotDetectedError
    with pytest.raises(FaceNotDetectedError):
        FaceMatchingService.verify_face(student, b"not-an-image-file-at-all-123456")

    # 4. Sinh viên chưa có vector 512 -> trả (False, 0.0, message)
    student_no_vec = SimpleNamespace(student_id="SV_EMPTY", face_embedding_512=None, face_embedding=[0.1] * 192)
    ok3, score3, msg3 = FaceMatchingService.verify_face(student_no_vec, sample_jpeg, face_service_client=fake_client_ok)
    assert ok3 is False
    assert score3 == 0.0
    assert "512" in msg3

    # 5. Mock handler của TV5 hoạt động đúng
    FaceMatchingService.set_mock_handler(lambda s, img: (True, 0.91, "Mock OK"))
    try:
        ok4, score4, msg4 = FaceMatchingService.verify_face(student, sample_jpeg)
        assert (ok4, score4, msg4) == (True, 0.91, "Mock OK")
    finally:
        FaceMatchingService.reset_mock_handler()

    assert issubclass(FaceServiceUnavailableError, Exception)

