import base64
import hashlib
import hmac
import json
import os
import time
from functools import wraps
from flask import current_app, request, jsonify, g
import uuid
from redis.exceptions import RedisError

ACCESS_TOKEN_EXPIRES = 3600          # 1 giờ
REFRESH_TOKEN_EXPIRES = 7 * 86400    # 7 ngày


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode((segment + padding).encode("ascii"))


def _get_secret() -> bytes:
    secret = current_app.config.get("SECRET_KEY")

    if not isinstance(secret, str) or not secret.strip():
        raise RuntimeError(
            "SECRET_KEY chưa được cấu hình."
        )

    if secret == "hkdn-default-secret-key-2026":
        raise RuntimeError(
            "Không được sử dụng JWT secret mặc định."
        )

    return secret.encode("utf-8")


def hash_password_sha256(password: str) -> str:
    """Băm mật khẩu bằng SHA-256 (tương thích 100% với DatabaseHelper.java trên Android)."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain_or_hashed: str, stored_hash: str) -> bool:
    if not plain_or_hashed or not stored_hash:
        return False
    # Trường hợp client gửi plain password, so khớp với SHA-256 trong DB
    if hash_password_sha256(plain_or_hashed).lower() == stored_hash.lower():
        return True
    # Trường hợp client đã băm SHA-256 trước khi gửi hoặc lưu trực tiếp
    if hmac.compare_digest(plain_or_hashed.lower(), stored_hash.lower()):
        return True
    return False


def create_jwt_token(admin_id: str, email: str, role: str, token_type: str = "access", expires_in: int = None) -> str:
    if expires_in is None:
        expires_in = ACCESS_TOKEN_EXPIRES if token_type == "access" else REFRESH_TOKEN_EXPIRES

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
    "sub": admin_id,
    "email": email,
    "role": role,
    "type": token_type,
    "jti": str(uuid.uuid4()),
    "iat": now,
    "exp": now + expires_in,
}

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(_get_secret(), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_jwt_token(token: str, expected_type: str = None) -> dict:
    if not token or not isinstance(token, str):
        raise ValueError("Token trống hoặc không hợp lệ.")

    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ValueError("Định dạng JWT không hợp lệ.")

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(_get_secret(), signing_input, hashlib.sha256).digest()

    try:
        actual_sig = _b64url_decode(sig_b64)
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Không thể giải mã JWT.") from exc

    if header.get("alg") != "HS256":
        raise ValueError("Thuật toán ký JWT không được hỗ trợ.")

    if not hmac.compare_digest(actual_sig, expected_sig):
        raise ValueError("Chữ ký JWT không hợp lệ.")

    now = int(time.time())
    exp = payload.get("exp")
    iat = payload.get("iat")

    if type(exp) is not int or type(iat) is not int:
        raise ValueError("Token thiếu thời gian hợp lệ.")

    if exp <= now:
        raise ValueError("Token đã hết hạn.")

    if iat > now:
        raise ValueError("Thời gian phát hành token không hợp lệ.")

    if not isinstance(payload.get("sub"), str) or not payload["sub"]:
        raise ValueError("Token thiếu thông tin tài khoản.")

    if expected_type and payload.get("type") != expected_type:
        raise ValueError(f"Yêu cầu loại token '{expected_type}'.")

    # Kiểm tra JWT có bị thu hồi trong Redis không
    from app.services.token_revocation_service import is_token_revoked

    if is_token_revoked(token):
        raise ValueError("Token đã bị thu hồi. Vui lòng đăng nhập lại.")

    return payload


def extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def require_auth(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        from app.models import Admin

        token = extract_bearer_token()

        if not token:
            return jsonify({
                "error": "UNAUTHORIZED",
                "message": "Thiếu Bearer token."
            }), 401

        try:
            payload = decode_jwt_token(
                token,
                expected_type="access"
            )

        except (ValueError, TypeError, OverflowError):
            return jsonify({
                "error": "INVALID_TOKEN",
                "message": "Token không hợp lệ, đã hết hạn hoặc đã bị thu hồi."
            }), 401

        except RedisError:
            return jsonify({
                "error": "AUTH_SERVICE_UNAVAILABLE",
                "message": "Dịch vụ xác thực tạm thời không khả dụng."
            }), 503

        admin_id = payload.get("sub")

        if not isinstance(admin_id, str) or not admin_id:
            return jsonify({
                "error": "INVALID_TOKEN",
                "message": "Token thiếu thông tin tài khoản."
            }), 401

        admin = Admin.query.filter_by(
            admin_id=admin_id,
            deleted_at=None
        ).first()

        if admin is None:
            return jsonify({
                "error": "UNAUTHORIZED",
                "message": "Tài khoản không tồn tại hoặc đã bị xóa."
            }), 401

        if admin.role not in ("ADMIN", "SUPER_ADMIN"):
            return jsonify({
                "error": "FORBIDDEN",
                "message": "Tài khoản không có quyền truy cập."
            }), 403

        g.current_admin = admin
        g.current_admin_id = admin.admin_id
        g.current_role = admin.role

        return func(*args, **kwargs)

    return wrapper

