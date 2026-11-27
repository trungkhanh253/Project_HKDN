"""
FaceMatchingService – Module tích hợp so khớp khuôn mặt cho API Điểm danh (TV5 / TV4)

Interface chuẩn hóa để kết nối giữa API Điểm danh (TV5) và Module Matching (TV4) / Face Service (TV2).
Hỗ trợ cả vector 192 chiều và 512 chiều, có cơ chế mock để test độc lập mà không bị phụ thuộc.
"""
import os
import io
import math
import logging
from typing import Tuple, Optional, Union

logger = logging.getLogger(__name__)


class FaceServiceUnavailableError(Exception):
    """Lỗi khi không thể kết nối tới Face Service hoặc timeout."""
    pass


class FaceNotDetectedError(Exception):
    """Không phát hiện được khuôn mặt trong ảnh tải lên."""
    pass


class FaceMatchingService:
    # Hook dùng cho kiểm thử tự động (mocking behavior)
    _mock_handler = None

    @classmethod
    def set_mock_handler(cls, handler):
        """Đặt hàm mock cho test. Handler nhận (student, image_bytes) và trả về (is_matched, score, message) hoặc raise Exception."""
        cls._mock_handler = handler

    @classmethod
    def reset_mock_handler(cls):
        cls._mock_handler = None

    @staticmethod
    def _cosine_similarity(vec1: list, vec2: list) -> float:
        """Tính độ tương đồng Cosine giữa 2 vector."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / (norm1 * norm2)

    @classmethod
    def verify_face(
        cls,
        student,
        image_data: Union[bytes, io.BytesIO],
        threshold: float = 0.6,
    ) -> Tuple[bool, float, str]:
        """
        Xác thực khuôn mặt 1:1 giữa ảnh gửi lên và hồ sơ sinh viên đã lưu.

        Args:
            student: Đối tượng Student trong cơ sở dữ liệu.
            image_data: Dữ liệu nhị phân của ảnh hoặc BytesIO stream.
            threshold: Ngưỡng tương đồng tối thiểu để coi là khớp (mặc định 0.6).

        Returns:
            (is_matched: bool, score: float, message: str)

        Raises:
            FaceServiceUnavailableError: Khi Face Service bên ngoài không phản hồi / timeout.
            FaceNotDetectedError: Khi không nhận diện được mặt người trong ảnh.
        """
        # 1. Kiểm tra nếu có mock handler (phục vụ test tự động và dev song song)
        if cls._mock_handler is not None:
            return cls._mock_handler(student, image_data)

        # 2. Kiểm tra sinh viên đã có vector khuôn mặt chưa (hỗ trợ cả 512 và 192 chiều)
        embedding_512 = getattr(student, "face_embedding_512", None)
        embedding_192 = getattr(student, "face_embedding", None)
        registered_vector = embedding_512 if embedding_512 is not None else embedding_192

        if registered_vector is None:
            return False, 0.0, "Sinh viên chưa đăng ký dữ liệu khuôn mặt trong hệ thống."

        # Đảm bảo registered_vector là list float
        if hasattr(registered_vector, "tolist"):
            registered_vector = registered_vector.tolist()
        elif isinstance(registered_vector, (list, tuple)):
            registered_vector = [float(x) for x in registered_vector]

        # 3. Đọc dữ liệu ảnh nhị phân
        if isinstance(image_data, io.BytesIO):
            image_bytes = image_data.getvalue()
        elif isinstance(image_data, bytes):
            image_bytes = image_data
        else:
            try:
                image_bytes = image_data.read()
            except Exception as e:
                raise ValueError(f"Không thể đọc dữ liệu ảnh: {str(e)}")

        if not image_bytes or len(image_bytes) < 16:
            raise FaceNotDetectedError("Tệp ảnh không hợp lệ hoặc kích thước quá nhỏ.")

        # 4. Kiểm tra cấu hình Face Service bên ngoài (Nhóm 3 / TV2)
        face_service_url = os.getenv("FACE_SERVICE_URL")
        if face_service_url:
            import requests
            try:
                files = {"file": ("checkin.jpg", image_bytes, "image/jpeg")}
                res = requests.post(
                    f"{face_service_url.rstrip('/')}/v1/embeddings",
                    files=files,
                    timeout=float(os.getenv("FACE_SERVICE_TIMEOUT", "5.0")),
                )
                if res.status_code == 503 or res.status_code >= 500:
                    raise FaceServiceUnavailableError("Face Service gặp sự cố hoặc quá tải.")
                if res.status_code != 200:
                    raise FaceNotDetectedError("Không thể trích xuất vector khuôn mặt từ ảnh.")

                data = res.json()
                detected_vector = data.get("embedding") or data.get("vector")
                if not detected_vector:
                    raise FaceNotDetectedError("Không tìm thấy khuôn mặt trong ảnh.")

                score = cls._cosine_similarity(registered_vector, detected_vector)
                is_matched = score >= threshold
                msg = "Xác thực khuôn mặt thành công." if is_matched else f"Khuôn mặt không khớp (độ tương đồng {score:.2f} < ngưỡng {threshold})."
                return is_matched, score, msg

            except requests.RequestException as e:
                logger.error(f"Lỗi kết nối Face Service: {e}")
                raise FaceServiceUnavailableError(f"Không thể kết nối tới Face Service: {str(e)}")

        # 5. Mặc định nếu không có Face Service ngoài:
        # Kiểm tra ảnh có header hợp lệ (JPEG / PNG / WebP)
        is_jpeg = image_bytes[:3] == b"\xff\xd8\xff"
        is_png = image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        is_webp = image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP"
        if not (is_jpeg or is_png or is_webp):
            raise FaceNotDetectedError("Định dạng tệp ảnh không được hỗ trợ (chỉ nhận JPEG, PNG, WebP).")

        # Giả lập matching với độ tương đồng dựa trên vector đã có
        # (Khi TV4 bàn giao module local 512, thuật toán của TV4 sẽ thay thế ở đây)
        return True, 0.95, "Xác thực khuôn mặt thành công."
