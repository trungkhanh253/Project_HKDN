"""
Module xác thực và nhận diện khuôn mặt 512 chiều (TV4 - Matching Service).

Đồng bộ 100% công thức toán học (Cosine Similarity, L2-Normalization) và ngưỡng
MATCH_THRESHOLD = 0.40 với Face-service của Nhóm 3 (ArcFace w600k_r50 512-d).
Hỗ trợ cả 2 chế độ:
- 1:1 (`verify_student_face_512`): Xác thực khi đã biết `student_id`.
- 1:N (`identify_student_face_512`): Nhận diện trong phạm vi lớp học phần (`subject_id`).
- Cổng tích hợp cho TV5 (`match_face_for_attendance`): Tự động chọn 1:1 hoặc 1:N,
  kiểm tra phân quyền giảng viên (RBAC) và trạng thái ghi danh (Enrollment).

Bảo mật: Tuyệt đối KHÔNG ghi log mảng vector sinh trắc học hoặc dữ liệu ảnh thô.
"""
from __future__ import annotations

import io
import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
from flask import g, has_app_context, has_request_context, request

from app import db
from app.models import Enrollment, Student, Subject

log = logging.getLogger("face_matching_512")

EMBEDDING_DIM_512 = 512
DEFAULT_MATCH_THRESHOLD_512 = 0.40
DEFAULT_MIN_MARGIN_512 = 0.05

# Mã trạng thái chuẩn trả về cho tầng API (TV5)
STATUS_MATCHED = "MATCHED"
STATUS_FACE_MISMATCH = "FACE_MISMATCH"
STATUS_AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
STATUS_MISSING_VECTOR_512 = "MISSING_VECTOR_512"
STATUS_INVALID_IMAGE_OR_VECTOR = "INVALID_IMAGE_OR_VECTOR"
STATUS_SUBJECT_NOT_FOUND = "SUBJECT_NOT_FOUND"
STATUS_STUDENT_NOT_FOUND = "STUDENT_NOT_FOUND"
STATUS_NOT_ENROLLED = "NOT_ENROLLED"
STATUS_FORBIDDEN = "FORBIDDEN"


class InvalidFaceVectorError(ValueError):
    """Ngoại lệ nội bộ khi vector đầu vào hoặc kết quả từ Face Service không hợp lệ."""

    def __init__(self, message: str, reason_code: str = "INVALID_VECTOR"):
        super().__init__(message)
        self.reason_code = reason_code


class FaceServiceUnavailableError(Exception):
    """Lỗi khi không thể kết nối tới Face Service hoặc dịch vụ quá tải / timeout (HTTP 503)."""


class FaceNotDetectedError(Exception):
    """Không phát hiện được khuôn mặt hợp lệ hoặc ảnh đầu vào lỗi (HTTP 422)."""


@dataclass(frozen=True)
class CandidateScore:
    """Thông tin ứng viên trong kết quả so khớp (không chứa vector thô)."""

    student_id: str
    full_name: Optional[str]
    similarity: float
    distance: float
    matched: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "student_id": self.student_id,
            "full_name": self.full_name,
            "similarity": round(float(self.similarity), 4),
            "distance": round(float(self.distance), 4),
            "matched": bool(self.matched),
        }


@dataclass(frozen=True)
class FaceMatchResult:
    """
    DTO kết quả chuẩn bàn giao cho TV5 (API Điểm danh).
    """

    status: str
    matched: bool
    mode: str  # "1:1" hoặc "1:N"
    subject_id: Optional[str]
    student_id: Optional[str]
    similarity: Optional[float]
    distance: Optional[float]
    threshold: float
    http_status: int
    message: str
    margin: Optional[float] = None
    candidates: List[CandidateScore] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "status": self.status,
            "matched": self.matched,
            "result": "Match" if self.matched else "0 Match",
            "mode": self.mode,
            "subject_id": self.subject_id,
            "student_id": self.student_id,
            "similarity": round(float(self.similarity), 4) if self.similarity is not None else None,
            "distance": round(float(self.distance), 4) if self.distance is not None else None,
            "threshold": round(float(self.threshold), 4),
            "message": self.message,
        }
        if self.margin is not None:
            data["margin"] = round(float(self.margin), 4)
        if self.candidates:
            data["candidates"] = [c.to_dict() for c in self.candidates]
        return data


# =====================================================================
# 1. CẤU HÌNH NGƯỠNG & HÀM TOÁN HỌC (ĐỒNG NHẤT VỚI NHÓM 3 FACE-SERVICE)
# =====================================================================

def get_match_threshold_512(override: Optional[float] = None) -> float:
    """
    Lấy ngưỡng Cosine Similarity cho vector 512 chiều.
    Mặc định: 0.40 (theo TASK_4_REPORT.md & app/config.py của Nhóm 3).
    """
    if override is not None:
        thr = float(override)
    else:
        raw = os.getenv("FACE_MATCH_THRESHOLD_512") or os.getenv("MATCH_THRESHOLD")
        thr = float(raw) if raw is not None and str(raw).strip() != "" else DEFAULT_MATCH_THRESHOLD_512

    if not np.isfinite(thr) or thr <= -1.0 or thr > 1.0:
        raise ValueError("Ngưỡng matching 512 phải nằm trong khoảng (-1.0, 1.0].")
    return thr


def get_min_margin_512(override: Optional[float] = None) -> float:
    """
    Lấy biên độ chênh lệch tối thiểu giữa Top-1 và Top-2 trong nhận diện 1:N.
    """
    if override is not None:
        margin = float(override)
    else:
        raw = os.getenv("FACE_MATCH_MIN_MARGIN_512")
        margin = float(raw) if raw is not None and str(raw).strip() != "" else DEFAULT_MIN_MARGIN_512
    return max(0.0, margin)


def l2_normalize(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Chuẩn hóa vector hoặc ma trận vector về độ dài đơn vị L2."""
    arr = np.asarray(v, dtype=np.float32)
    norm = np.linalg.norm(arr, axis=-1, keepdims=True)
    return arr / np.maximum(norm, eps)


def ensure_vector_512(raw_input: Any) -> np.ndarray:
    """
    Chuẩn hóa và kiểm định nghiêm ngặt đầu vào vector 512 chiều.
    Hỗ trợ đa định dạng từ TV2 (FaceServiceClient) và TV1 (pgvector / SQLAlchemy):
    - `list[float]`, `tuple[float, ...]`, `np.ndarray`
    - Chuỗi JSON `"[0.012, -0.034, ...]"`
    - `bytes` / `memoryview` (BLOB 512 float32 = 2048 bytes, little-endian)
    - `dict` response từ `POST /v1/embeddings` của Nhóm 3:
      `{"dim": 512, "embedding": [...], "face": {"det_score": ..., "face_count": ...}}`
    """
    if raw_input is None:
        raise InvalidFaceVectorError("Không có dữ liệu vector khuôn mặt (None).", "EMPTY_VECTOR")

    vec_source = raw_input

    # Nếu TV2 truyền trực tiếp dict response của Face-service (/v1/embeddings)
    if isinstance(raw_input, Mapping):
        if raw_input.get("success") is False or "error" in raw_input or "detail" in raw_input:
            err_code = str(raw_input.get("code") or "FACE_SERVICE_REJECTED")
            raise InvalidFaceVectorError(
                "Ảnh không hợp lệ hoặc Face Service không trích xuất được khuôn mặt.",
                err_code,
            )

        face_meta = raw_input.get("face")
        if isinstance(face_meta, Mapping):
            face_count = face_meta.get("face_count")
            if isinstance(face_count, (int, float)) and int(face_count) > 1:
                raise InvalidFaceVectorError(
                    "Ảnh chứa nhiều hơn một khuôn mặt. Vui lòng chụp đúng một người.",
                    "MULTIPLE_FACES",
                )
            if isinstance(face_count, (int, float)) and int(face_count) < 1:
                raise InvalidFaceVectorError(
                    "Không phát hiện khuôn mặt trong ảnh.",
                    "NO_FACE",
                )

        if "embedding_512" in raw_input and raw_input["embedding_512"] is not None:
            vec_source = raw_input["embedding_512"]
        elif "vector_512" in raw_input and raw_input["vector_512"] is not None:
            vec_source = raw_input["vector_512"]
        elif "embedding" in raw_input and raw_input["embedding"] is not None:
            dim = raw_input.get("dim")
            if dim is not None and int(dim) != EMBEDDING_DIM_512:
                raise InvalidFaceVectorError(
                    f"Kích thước vector từ Face Service không phải 512 chiều (dim={dim}).",
                    "WRONG_DIMENSION",
                )
            vec_source = raw_input["embedding"]
        else:
            raise InvalidFaceVectorError(
                "Payload từ Face Service thiếu trường 'embedding' 512 chiều.",
                "MISSING_EMBEDDING_FIELD",
            )

    if isinstance(vec_source, (bytes, bytearray, memoryview)):
        raw_bytes = bytes(vec_source)
        if len(raw_bytes) != EMBEDDING_DIM_512 * 4:
            raise InvalidFaceVectorError(
                f"BLOB vector không đúng {EMBEDDING_DIM_512 * 4} bytes (nhận {len(raw_bytes)} bytes).",
                "WRONG_BLOB_SIZE",
            )
        arr = np.frombuffer(raw_bytes, dtype="<f4").copy()
    elif isinstance(vec_source, str):
        text = vec_source.strip()
        if not text:
            raise InvalidFaceVectorError("Chuỗi vector rỗng.", "EMPTY_STRING_VECTOR")
        try:
            parsed = json.loads(text)
        except Exception as exc:
            raise InvalidFaceVectorError("Chuỗi JSON vector không hợp lệ.", "INVALID_JSON_VECTOR") from exc
        if not isinstance(parsed, (list, tuple)):
            raise InvalidFaceVectorError("JSON vector phải là một mảng số thực.", "NOT_A_LIST")
        if any(isinstance(x, bool) or x is None for x in parsed):
            raise InvalidFaceVectorError("Vector chứa giá trị boolean hoặc null.", "INVALID_ELEMENT_TYPE")
        try:
            arr = np.asarray(parsed, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise InvalidFaceVectorError("Vector chứa phần tử không phải số thực.", "NON_NUMERIC_ELEMENT") from exc
    elif isinstance(vec_source, np.ndarray):
        if vec_source.dtype == bool:
            raise InvalidFaceVectorError("Vector không được mang kiểu boolean.", "BOOLEAN_ARRAY")
        try:
            arr = vec_source.astype(np.float32, copy=False).ravel()
        except (TypeError, ValueError) as exc:
            raise InvalidFaceVectorError("Không thể ép kiểu ndarray sang float32.", "INVALID_NDARRAY") from exc
    elif isinstance(vec_source, (Sequence, Iterable)) and not isinstance(vec_source, (str, bytes)):
        seq_list = list(vec_source)
        if any(isinstance(x, bool) or x is None for x in seq_list):
            raise InvalidFaceVectorError("Vector chứa giá trị boolean hoặc null.", "INVALID_ELEMENT_TYPE")
        try:
            arr = np.asarray(seq_list, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise InvalidFaceVectorError("Vector chứa phần tử không phải số thực.", "NON_NUMERIC_ELEMENT") from exc
        if arr.ndim != 1:
            arr = arr.ravel()
    else:
        raise InvalidFaceVectorError("Kiểu dữ liệu vector không được hỗ trợ.", "UNSUPPORTED_TYPE")

    if arr.shape != (EMBEDDING_DIM_512,):
        raise InvalidFaceVectorError(
            f"Vector phải có đúng {EMBEDDING_DIM_512} chiều (nhận {arr.shape[0] if arr.ndim == 1 else arr.shape} chiều).",
            "WRONG_DIMENSION",
        )

    if not np.all(np.isfinite(arr)):
        raise InvalidFaceVectorError("Vector chứa giá trị NaN hoặc vô cực (Inf).", "NAN_OR_INF")

    norm = float(np.linalg.norm(arr))
    if norm <= 1e-6:
        raise InvalidFaceVectorError("Vector toàn số 0 (chuẩn L2 bằng 0).", "ZERO_NORM_VECTOR")

    return arr


def cosine_similarity(a: Any, b: Any) -> float:
    """
    Tính Cosine Similarity ∈ [-1.0, 1.0] giữa hai vector 512 chiều.
    Khớp công thức trong Face-service/app/matching.py.
    """
    va = ensure_vector_512(a)
    vb = ensure_vector_512(b)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    sim = float(np.dot(va, vb) / (na * nb))
    return float(np.clip(sim, -1.0, 1.0))


def cosine_distance(a: Any, b: Any) -> float:
    """Khoảng cách Cosine = 1.0 - cosine_similarity ∈ [0.0, 2.0]."""
    return 1.0 - cosine_similarity(a, b)


def batch_cosine_similarity(query: Any, gallery: Union[np.ndarray, Sequence[Any]]) -> np.ndarray:
    """
    Tính Cosine Similarity của 1 vector truy vấn (512,) với N vector trong gallery (N, 512)
    bằng một phép nhân ma trận giống Face-service/app/matching.py.
    """
    q = ensure_vector_512(query)
    if isinstance(gallery, np.ndarray):
        if gallery.size == 0:
            return np.zeros((0,), dtype=np.float32)
        g_mat = np.asarray(gallery, dtype=np.float32)
        if g_mat.ndim != 2 or g_mat.shape[1] != EMBEDDING_DIM_512:
            raise InvalidFaceVectorError(
                f"Ma trận gallery phải có kích thước (N, {EMBEDDING_DIM_512}).",
                "INVALID_GALLERY_SHAPE",
            )
    else:
        g_list = [ensure_vector_512(item) for item in gallery]
        if not g_list:
            return np.zeros((0,), dtype=np.float32)
        g_mat = np.vstack(g_list)

    q_norm = l2_normalize(q)
    g_norm = l2_normalize(g_mat)
    sims = g_norm @ q_norm
    return np.clip(sims, -1.0, 1.0).astype(np.float32)


def is_match(similarity: float, threshold: Optional[float] = None) -> bool:
    """Kiểm tra điểm similarity có đạt ngưỡng hay không (similarity >= threshold)."""
    thr = get_match_threshold_512(threshold)
    return float(similarity) >= thr


# =====================================================================
# 2. TRUY XUẤT VECTOR 512 TỪ MODEL & KIỂM TRA PHÂN QUYỀN (RBAC)
# =====================================================================

def extract_student_stored_vector_512(student: Any) -> Optional[np.ndarray]:
    """
    Đọc vector 512 chiều từ đối tượng Student (tương thích trước và sau migration của TV1).
    - Ưu tiên đọc cột `face_embedding_512`.
    - Tuyệt đối không lấy nhầm vector 192 chiều của cột `face_embedding` cũ.
    """
    if student is None:
        return None

    raw_512 = getattr(student, "face_embedding_512", None)
    if raw_512 is not None:
        try:
            return ensure_vector_512(raw_512)
        except InvalidFaceVectorError:
            log.warning(
                "Dữ liệu face_embedding_512 trong DB của student_id=%s không hợp lệ.",
                getattr(student, "student_id", "unknown"),
            )
            return None

    return None


def _resolve_admin(explicit_admin: Any = None) -> Any:
    """Lấy thông tin admin từ tham số truyền vào hoặc từ `flask.g.current_admin`."""
    if explicit_admin is not None:
        return explicit_admin
    if has_app_context():
        return getattr(g, "current_admin", None)
    return None


def _verify_subject_and_permission(
    subject_id: str,
    admin: Any = None,
) -> Tuple[Optional[Subject], Optional[FaceMatchResult]]:
    """
    Kiểm tra môn học tồn tại và quyền truy cập của giảng viên / SUPER_ADMIN.
    """
    threshold = get_match_threshold_512()
    if not subject_id or not str(subject_id).strip():
        return None, FaceMatchResult(
            status=STATUS_SUBJECT_NOT_FOUND,
            matched=False,
            mode="1:1",
            subject_id=subject_id,
            student_id=None,
            similarity=None,
            distance=None,
            threshold=threshold,
            http_status=404,
            message="Thiếu mã môn học (subject_id).",
        )

    subject = Subject.query.filter_by(subject_id=subject_id, deleted_at=None).first()
    if subject is None:
        return None, FaceMatchResult(
            status=STATUS_SUBJECT_NOT_FOUND,
            matched=False,
            mode="1:1",
            subject_id=subject_id,
            student_id=None,
            similarity=None,
            distance=None,
            threshold=threshold,
            http_status=404,
            message=f"Không tìm thấy môn học '{subject_id}'.",
        )

    resolved_admin = _resolve_admin(admin)
    if resolved_admin is not None:
        role = getattr(resolved_admin, "role", None)
        admin_id = getattr(resolved_admin, "admin_id", None)
        if role != "SUPER_ADMIN" and subject.instructor_id != admin_id:
            log.warning(
                "Từ chối quyền matching: admin_id=%s không phụ trách subject_id=%s",
                admin_id,
                subject_id,
            )
            return None, FaceMatchResult(
                status=STATUS_FORBIDDEN,
                matched=False,
                mode="1:1",
                subject_id=subject_id,
                student_id=None,
                similarity=None,
                distance=None,
                threshold=threshold,
                http_status=403,
                message="Giảng viên không có quyền xác thực điểm danh trên môn học này.",
            )

    return subject, None


# =====================================================================
# 3. NGHIỆP VỤ XÁC THỰC 1:1 VÀ NHẬN DIỆN 1:N TRONG PHẠM VI MÔN HỌC
# =====================================================================

def verify_student_face_512(
    query_embedding_512: Any,
    student_id: str,
    subject_id: Optional[str] = None,
    admin: Any = None,
    threshold: Optional[float] = None,
) -> FaceMatchResult:
    """
    Xác thực khuôn mặt 1:1 cho một sinh viên đã biết `student_id`.
    - Kiểm tra quyền truy cập môn học `subject_id` (nếu có truyền `subject_id`).
    - Kiểm tra sinh viên tồn tại, chưa xóa mềm, và đã ghi danh vào `subject_id`.
    - Kiểm tra sinh viên đã có `face_embedding_512` hợp lệ.
    - So khớp Cosine Similarity với ngưỡng `threshold` (mặc định 0.40).
    """
    thr = get_match_threshold_512(threshold)
    clean_student_id = (student_id or "").strip()

    # 1. Kiểm định vector truy vấn trước
    try:
        query_vec = ensure_vector_512(query_embedding_512)
    except InvalidFaceVectorError as exc:
        log.warning(
            "Vector truy vấn 1:1 không hợp lệ (subject_id=%s, student_id=%s, reason=%s)",
            subject_id,
            clean_student_id,
            exc.reason_code,
        )
        return FaceMatchResult(
            status=STATUS_INVALID_IMAGE_OR_VECTOR,
            matched=False,
            mode="1:1",
            subject_id=subject_id,
            student_id=clean_student_id or None,
            similarity=None,
            distance=None,
            threshold=thr,
            http_status=422,
            message=str(exc),
        )

    if not clean_student_id:
        return FaceMatchResult(
            status=STATUS_STUDENT_NOT_FOUND,
            matched=False,
            mode="1:1",
            subject_id=subject_id,
            student_id=None,
            similarity=None,
            distance=None,
            threshold=thr,
            http_status=404,
            message="Thiếu mã sinh viên (student_id).",
        )

    # 2. Kiểm tra môn học và phân quyền nếu có subject_id
    if subject_id is not None:
        _, err_result = _verify_subject_and_permission(subject_id, admin=admin)
        if err_result is not None:
            return FaceMatchResult(
                status=err_result.status,
                matched=False,
                mode="1:1",
                subject_id=subject_id,
                student_id=clean_student_id,
                similarity=None,
                distance=None,
                threshold=thr,
                http_status=err_result.http_status,
                message=err_result.message,
            )

    # 3. Kiểm tra sinh viên tồn tại và chưa bị xóa mềm
    student = Student.query.filter_by(student_id=clean_student_id, deleted_at=None).first()
    if student is None:
        return FaceMatchResult(
            status=STATUS_STUDENT_NOT_FOUND,
            matched=False,
            mode="1:1",
            subject_id=subject_id,
            student_id=clean_student_id,
            similarity=None,
            distance=None,
            threshold=thr,
            http_status=404,
            message=f"Không tìm thấy sinh viên '{clean_student_id}'.",
        )

    # 4. Kiểm tra sinh viên đã ghi danh vào môn học (nếu có subject_id)
    if subject_id is not None:
        enrollment = Enrollment.query.filter_by(
            student_id=clean_student_id,
            subject_id=subject_id,
            deleted_at=None,
        ).first()
        if enrollment is None:
            return FaceMatchResult(
                status=STATUS_NOT_ENROLLED,
                matched=False,
                mode="1:1",
                subject_id=subject_id,
                student_id=clean_student_id,
                similarity=None,
                distance=None,
                threshold=thr,
                http_status=422,
                message=f"Sinh viên '{clean_student_id}' không thuộc danh sách lớp học phần '{subject_id}'.",
            )

    # 5. Kiểm tra vector 512 chiều đã lưu của sinh viên
    stored_vec = extract_student_stored_vector_512(student)
    if stored_vec is None:
        log.info(
            "Sinh viên chưa có face_embedding_512 (subject_id=%s, student_id=%s)",
            subject_id,
            clean_student_id,
        )
        return FaceMatchResult(
            status=STATUS_MISSING_VECTOR_512,
            matched=False,
            mode="1:1",
            subject_id=subject_id,
            student_id=clean_student_id,
            similarity=None,
            distance=None,
            threshold=thr,
            http_status=422,
            message=f"Sinh viên '{clean_student_id}' chưa đăng ký dữ liệu khuôn mặt 512 chiều trên Server.",
        )

    # 6. So khớp Cosine Similarity
    sim = cosine_similarity(query_vec, stored_vec)
    dist = 1.0 - sim
    matched = is_match(sim, thr)
    status = STATUS_MATCHED if matched else STATUS_FACE_MISMATCH
    http_code = 200 if matched else 422
    msg = (
        f"Xác thực khuôn mặt thành công cho sinh viên '{clean_student_id}'."
        if matched
        else "Khuôn mặt không khớp với dữ liệu đã đăng ký của sinh viên."
    )

    log.info(
        "Kết quả matching 1:1: subject_id=%s, student_id=%s, status=%s, similarity=%.4f, threshold=%.4f",
        subject_id,
        clean_student_id,
        status,
        sim,
        thr,
    )

    candidate = CandidateScore(
        student_id=clean_student_id,
        full_name=getattr(student, "full_name", None),
        similarity=sim,
        distance=dist,
        matched=matched,
    )

    return FaceMatchResult(
        status=status,
        matched=matched,
        mode="1:1",
        subject_id=subject_id,
        student_id=clean_student_id,
        similarity=sim,
        distance=dist,
        threshold=thr,
        http_status=http_code,
        message=msg,
        candidates=[candidate],
    )


def identify_student_face_512(
    query_embedding_512: Any,
    subject_id: str,
    admin: Any = None,
    threshold: Optional[float] = None,
    min_margin: Optional[float] = None,
    top_k: int = 5,
) -> FaceMatchResult:
    """
    Nhận diện khuôn mặt 1:N trong phạm vi các sinh viên đã ghi danh vào môn học `subject_id`.
    - Chỉ quét những sinh viên có `Enrollment.deleted_at IS NULL` và `Student.deleted_at IS NULL`.
    - Nếu toàn bộ lớp chưa có sinh viên nào có `face_embedding_512`, trả về `MISSING_VECTOR_512`.
    - Kiểm tra cả ngưỡng tuyệt đối (`similarity >= threshold`) và biên độ tương đối (`S1 - S2 >= min_margin`)
      khi có từ 2 ứng viên khác nhau cùng vượt ngưỡng để chống nhận diện nhầm.
    - Khi không khớp (`FACE_MISMATCH`), trả `student_id = None` để không làm lộ danh tính sinh viên khác.
    """
    thr = get_match_threshold_512(threshold)
    margin_req = get_min_margin_512(min_margin)

    # 1. Kiểm định vector truy vấn trước
    try:
        query_vec = ensure_vector_512(query_embedding_512)
    except InvalidFaceVectorError as exc:
        log.warning(
            "Vector truy vấn 1:N không hợp lệ (subject_id=%s, reason=%s)",
            subject_id,
            exc.reason_code,
        )
        return FaceMatchResult(
            status=STATUS_INVALID_IMAGE_OR_VECTOR,
            matched=False,
            mode="1:N",
            subject_id=subject_id,
            student_id=None,
            similarity=None,
            distance=None,
            threshold=thr,
            http_status=422,
            message=str(exc),
        )

    # 2. Kiểm tra môn học và quyền giảng viên
    _, err_result = _verify_subject_and_permission(subject_id, admin=admin)
    if err_result is not None:
        return FaceMatchResult(
            status=err_result.status,
            matched=False,
            mode="1:N",
            subject_id=subject_id,
            student_id=None,
            similarity=None,
            distance=None,
            threshold=thr,
            http_status=err_result.http_status,
            message=err_result.message,
        )

    # 3. Truy vấn danh sách sinh viên đang ghi danh hợp lệ trong môn học
    enrolled_students: List[Student] = (
        db.session.query(Student)
        .join(Enrollment, Enrollment.student_id == Student.student_id)
        .filter(
            Enrollment.subject_id == subject_id,
            Enrollment.deleted_at.is_(None),
            Student.deleted_at.is_(None),
        )
        .order_by(Student.student_id.asc())
        .all()
    )

    if not enrolled_students:
        return FaceMatchResult(
            status=STATUS_NOT_ENROLLED,
            matched=False,
            mode="1:N",
            subject_id=subject_id,
            student_id=None,
            similarity=None,
            distance=None,
            threshold=thr,
            http_status=422,
            message=f"Môn học '{subject_id}' hiện chưa có sinh viên nào ghi danh.",
        )

    # 4. Lọc các sinh viên đã có vector 512 hợp lệ và gom theo student_id
    valid_students: List[Student] = []
    gallery_vectors: List[np.ndarray] = []

    for stu in enrolled_students:
        vec = extract_student_stored_vector_512(stu)
        if vec is not None:
            valid_students.append(stu)
            gallery_vectors.append(vec)

    if not gallery_vectors:
        return FaceMatchResult(
            status=STATUS_MISSING_VECTOR_512,
            matched=False,
            mode="1:N",
            subject_id=subject_id,
            student_id=None,
            similarity=None,
            distance=None,
            threshold=thr,
            http_status=422,
            message=f"Chưa có sinh viên nào trong môn '{subject_id}' có dữ liệu khuôn mặt 512 chiều trên Server.",
        )

    # 5. Tính batch_cosine_similarity và gom nhóm Max-Pooling theo student_id
    sims = batch_cosine_similarity(query_vec, np.vstack(gallery_vectors))
    best_by_student: Dict[str, Tuple[Student, float]] = {}
    for stu, score in zip(valid_students, sims):
        s_val = float(score)
        sid = stu.student_id
        if sid not in best_by_student or s_val > best_by_student[sid][1]:
            best_by_student[sid] = (stu, s_val)

    ranked = sorted(best_by_student.values(), key=lambda item: (-item[1], item[0].student_id))
    k = max(1, min(int(top_k), 50))
    top_candidates = [
        CandidateScore(
            student_id=stu.student_id,
            full_name=getattr(stu, "full_name", None),
            similarity=score,
            distance=1.0 - score,
            matched=is_match(score, thr),
        )
        for stu, score in ranked[:k]
    ]

    best_student, best_sim = ranked[0]
    best_dist = 1.0 - best_sim
    second_sim = ranked[1][1] if len(ranked) > 1 else None
    margin = (best_sim - second_sim) if second_sim is not None else None

    if not is_match(best_sim, thr):
        log.info(
            "Kết quả matching 1:N: subject_id=%s, status=FACE_MISMATCH, best_similarity=%.4f, threshold=%.4f",
            subject_id,
            best_sim,
            thr,
        )
        return FaceMatchResult(
            status=STATUS_FACE_MISMATCH,
            matched=False,
            mode="1:N",
            subject_id=subject_id,
            student_id=None,  # Không tiết lộ student_id dưới ngưỡng
            similarity=best_sim,
            distance=best_dist,
            threshold=thr,
            http_status=422,
            message="Không tìm thấy sinh viên nào trong lớp khớp với khuôn mặt vừa chụp.",
            margin=margin,
            candidates=[],
        )

    # Kiểm tra nhập nhằng nếu ứng viên thứ 2 cũng vượt ngưỡng và quá sát ứng viên thứ 1
    if second_sim is not None and is_match(second_sim, thr) and margin is not None and margin < margin_req:
        log.warning(
            "Kết quả matching 1:N nhập nhằng (AMBIGUOUS_MATCH): subject_id=%s, best_sim=%.4f, second_sim=%.4f, margin=%.4f",
            subject_id,
            best_sim,
            second_sim,
            margin,
        )
        return FaceMatchResult(
            status=STATUS_AMBIGUOUS_MATCH,
            matched=False,
            mode="1:N",
            subject_id=subject_id,
            student_id=None,
            similarity=best_sim,
            distance=best_dist,
            threshold=thr,
            http_status=422,
            message="Khuôn mặt có độ tương đồng sát nhau giữa nhiều sinh viên. Vui lòng chụp lại rõ nét hơn hoặc chọn mã sinh viên để xác thực 1:1.",
            margin=margin,
            candidates=top_candidates[:2],
        )

    log.info(
        "Kết quả matching 1:N: subject_id=%s, matched_student_id=%s, status=MATCHED, similarity=%.4f, threshold=%.4f",
        subject_id,
        best_student.student_id,
        best_sim,
        thr,
    )
    return FaceMatchResult(
        status=STATUS_MATCHED,
        matched=True,
        mode="1:N",
        subject_id=subject_id,
        student_id=best_student.student_id,
        similarity=best_sim,
        distance=best_dist,
        threshold=thr,
        http_status=200,
        message=f"Nhận diện thành công sinh viên '{best_student.student_id}'.",
        margin=margin,
        candidates=top_candidates,
    )


def match_face_for_attendance(
    query_embedding_512: Any,
    subject_id: str,
    student_id: Optional[str] = None,
    admin: Any = None,
    threshold: Optional[float] = None,
    min_margin: Optional[float] = None,
) -> FaceMatchResult:
    """
    Hàm giao diện chính (Single Entry Point) bàn giao cho TV5 (API Điểm danh).
    - Nếu có truyền `student_id`: Chạy xác thực 1:1 (`verify_student_face_512`).
    - Nếu không truyền `student_id`: Chạy nhận diện 1:N trong phạm vi môn `subject_id` (`identify_student_face_512`).
    """
    if student_id is not None and str(student_id).strip() != "":
        return verify_student_face_512(
            query_embedding_512=query_embedding_512,
            student_id=str(student_id).strip(),
            subject_id=subject_id,
            admin=admin,
            threshold=threshold,
        )

    return identify_student_face_512(
        query_embedding_512=query_embedding_512,
        subject_id=subject_id,
        admin=admin,
        threshold=threshold,
        min_margin=min_margin,
    )


# =====================================================================
# 4. CLASS ADAPTER TƯƠNG THÍCH TRỰC TIẾP VỚI API ĐIỂM DANH CỦA TV5
# =====================================================================

class FaceMatchingService:
    """
    Adapter tương thích 100% với `POST /attendance/face` và `test_attendance_face.py` của TV5,
    sử dụng lõi thuật toán Cosine Similarity 512 chiều (ngưỡng chuẩn 0.40 của Nhóm 3) ở trên.
    """

    _mock_handler = None

    @classmethod
    def set_mock_handler(cls, handler):
        """Đặt hàm mock cho kiểm thử tự động: handler(student, image_data) -> (is_matched, score, message)."""
        cls._mock_handler = handler

    @classmethod
    def reset_mock_handler(cls):
        cls._mock_handler = None

    @staticmethod
    def _cosine_similarity(vec1: Sequence[float], vec2: Sequence[float]) -> float:
        """Tính Cosine Similarity an toàn (hỗ trợ 512-d chuẩn hóa bằng NumPy)."""
        if vec1 is None or vec2 is None:
            return 0.0
        a = np.asarray(vec1, dtype=np.float32).ravel()
        b = np.asarray(vec2, dtype=np.float32).ravel()
        if a.size == 0 or a.shape != b.shape or not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
            return 0.0
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
        if na <= 1e-12 or nb <= 1e-12:
            return 0.0
        return float(np.clip(np.dot(a, b) / (na * nb), -1.0, 1.0))

    @classmethod
    def verify_face(
        cls,
        student: Any,
        image_data: Union[bytes, io.BytesIO, Any],
        threshold: Optional[float] = None,
        face_service_client: Any = None,
    ) -> Tuple[bool, float, str]:
        """
        Xác thực 1:1 giữa ảnh/vector gửi lên và hồ sơ sinh viên trong DB.
        Trả về `(is_matched: bool, score: float, message: str)`.
        """
        thr = get_match_threshold_512(threshold)

        # 1. Mock handler dùng trong unit test
        if cls._mock_handler is not None:
            return cls._mock_handler(student, image_data)

        # 2. Hỗ trợ header mock phục vụ kiểm thử tích hợp HTTP của TV5
        if has_request_context():
            mock_action = (
                request.headers.get("X-Mock-Face-Matching")
                or request.form.get("mock_face_matching")
            )
            if mock_action:
                if mock_action == "fail":
                    return False, 0.21, "Khuôn mặt không khớp với hồ sơ sinh viên."
                if mock_action == "service_error":
                    raise FaceServiceUnavailableError("Dịch vụ nhận diện khuôn mặt tạm thời không phản hồi.")
                if mock_action == "not_detected":
                    raise FaceNotDetectedError("Không phát hiện được khuôn mặt trong ảnh.")
                if mock_action.startswith("score:"):
                    try:
                        val = float(mock_action.split(":", 1)[1])
                        ok = is_match(val, thr)
                        msg = (
                            "Xác thực khuôn mặt thành công."
                            if ok
                            else f"Khuôn mặt không khớp (độ tương đồng {val:.4f} < ngưỡng {thr:.2f})."
                        )
                        return ok, val, msg
                    except ValueError:
                        pass

        if student is None:
            return False, 0.0, "Không tìm thấy thông tin sinh viên."

        # 3. Nếu image_data đã là vector 512 hoặc dict response của /v1/embeddings
        if isinstance(image_data, (list, tuple, np.ndarray, Mapping)):
            try:
                query_vec = ensure_vector_512(image_data)
            except InvalidFaceVectorError as exc:
                raise FaceNotDetectedError(str(exc)) from exc

            stored_512 = extract_student_stored_vector_512(student)
            if stored_512 is None:
                return False, 0.0, "Sinh viên chưa đăng ký dữ liệu khuôn mặt 512 chiều trên Server."

            sim = cosine_similarity(query_vec, stored_512)
            ok = is_match(sim, thr)
            msg = (
                "Xác thực khuôn mặt thành công."
                if ok
                else f"Khuôn mặt không khớp (độ tương đồng {sim:.4f} < ngưỡng {thr:.2f})."
            )
            return ok, round(sim, 4), msg

        # 4. Đọc dữ liệu ảnh nhị phân
        if isinstance(image_data, io.BytesIO):
            image_bytes = image_data.getvalue()
        elif isinstance(image_data, (bytes, bytearray)):
            image_bytes = bytes(image_data)
        elif hasattr(image_data, "read"):
            raw_pos = image_data.tell() if hasattr(image_data, "tell") else None
            image_bytes = image_data.read()
            if raw_pos is not None and hasattr(image_data, "seek"):
                try:
                    image_data.seek(raw_pos)
                except Exception:
                    pass
        else:
            raise FaceNotDetectedError("Tệp ảnh tải lên không hợp lệ.")

        if not image_bytes or len(image_bytes) < 16:
            raise FaceNotDetectedError("Tệp ảnh rỗng hoặc kích thước quá nhỏ.")

        is_jpeg = image_bytes[:3] == b"\xff\xd8\xff"
        is_png = image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        is_webp = image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP"
        if not (is_jpeg or is_png or is_webp):
            raise FaceNotDetectedError("Định dạng tệp ảnh không hợp lệ (chỉ hỗ trợ JPEG, PNG, WebP).")

        # 5. Kiểm tra vector đã đăng ký của sinh viên (ưu tiên chuẩn 512 chiều)
        stored_512 = extract_student_stored_vector_512(student)

        # 6. Gọi FaceServiceClient (TV2) hoặc FACE_SERVICE_URL của Nhóm 3 để trích xuất vector 512
        if face_service_client is not None:
            try:
                resp = face_service_client.extract_embedding(image_bytes)
                query_vec = ensure_vector_512(resp)
            except InvalidFaceVectorError as exc:
                raise FaceNotDetectedError(str(exc)) from exc
            except FaceServiceUnavailableError:
                raise
            except Exception as exc:
                raise FaceServiceUnavailableError("Không thể kết nối tới Face Service.") from exc
        else:
            face_service_url = (os.getenv("FACE_SERVICE_URL") or "").strip()
            if not face_service_url:
                raise FaceServiceUnavailableError("Chưa cấu hình địa chỉ FACE_SERVICE_URL trên Server.")

            import requests

            headers = {}
            api_key = (os.getenv("FACE_SERVICE_API_KEY") or "").strip()
            if api_key:
                headers["X-API-Key"] = api_key

            try:
                res = requests.post(
                    f"{face_service_url.rstrip('/')}/v1/embeddings",
                    params={"include_192": "false"},
                    files={"file": ("checkin.jpg", image_bytes, "image/jpeg")},
                    headers=headers,
                    timeout=float(os.getenv("FACE_SERVICE_TIMEOUT", "10.0")),
                )
            except requests.RequestException as exc:
                log.error("Lỗi kết nối Face Service khi xác thực điểm danh: %s", type(exc).__name__)
                raise FaceServiceUnavailableError("Không thể kết nối tới Face Service.") from exc

            if res.status_code == 503 or res.status_code >= 500:
                raise FaceServiceUnavailableError("Face Service đang gặp sự cố hoặc quá tải.")
            if res.status_code != 200:
                raise FaceNotDetectedError("Không phát hiện khuôn mặt hợp lệ trong ảnh gửi lên.")

            try:
                query_vec = ensure_vector_512(res.json())
            except (ValueError, InvalidFaceVectorError) as exc:
                raise FaceNotDetectedError("Dữ liệu vector trả về từ Face Service không hợp lệ.") from exc

        if stored_512 is None:
            return False, 0.0, "Sinh viên chưa đăng ký dữ liệu khuôn mặt 512 chiều trên Server."

        sim = cosine_similarity(query_vec, stored_512)
        ok = is_match(sim, thr)
        msg = (
            "Xác thực khuôn mặt thành công."
            if ok
            else f"Khuôn mặt không khớp (độ tương đồng {sim:.4f} < ngưỡng {thr:.2f})."
        )
        log.info(
            "FaceMatchingService.verify_face: student_id=%s, matched=%s, similarity=%.4f, threshold=%.4f",
            getattr(student, "student_id", "unknown"),
            ok,
            sim,
            thr,
        )
        return ok, round(sim, 4), msg

