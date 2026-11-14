
import hashlib
import secrets
import time

from app import db
from app.models import Admin
from app.auth import hash_password_sha256


RESET_TOKEN_TTL_SECONDS = 120


def _hash_token(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def create_password_reset_token(email: str):
    """
    Tạo reset token cho tài khoản Admin.

    Token có hiệu lực trong 120 giây.
    Chỉ lưu SHA-256 của token trong database.
    """
    admin = Admin.query.filter_by(email=email).first()

    if admin is None:
        return None

    token = secrets.token_urlsafe(32)

    admin.reset_token = _hash_token(token)
    admin.expire_at = (
        int(time.time() * 1000)
        + RESET_TOKEN_TTL_SECONDS * 1000
    )

    db.session.commit()

    return token


def is_reset_token_valid(email: str, token: str) -> bool:
    """
    Kiểm tra token và thời gian hết hạn.
    """
    if not email or not token:
        return False

    admin = Admin.query.filter_by(email=email).first()

    if admin is None:
        return False

    if not admin.reset_token or admin.expire_at is None:
        return False

    current_time = int(time.time() * 1000)

    if current_time > admin.expire_at:
        return False

    provided_hash = _hash_token(token)

    return secrets.compare_digest(
        admin.reset_token,
        provided_hash
    )



def reset_password(
    email: str,
    token: str,
    new_password: str
) -> bool:
    if not email or not token:
        return False

    current_time = int(time.time() * 1000)
    token_hash = _hash_token(token)

    # UPDATE có điều kiện giúp token chỉ được sử dụng một lần.
    rows_updated = (
        db.session.query(Admin)
        .filter(
            Admin.email == email,
            Admin.reset_token == token_hash,
            Admin.expire_at.isnot(None),
            Admin.expire_at >= current_time,
        )
        .update(
            {
                Admin.password: hash_password_sha256(new_password),
                Admin.reset_token: None,
                Admin.expire_at: None,
            },
            synchronize_session=False,
        )
    )

    db.session.commit()

    return rows_updated == 1

