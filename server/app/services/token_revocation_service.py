
import hashlib
import os
import time

import redis
from flask import current_app


def _get_redis_client():
    redis_url = current_app.config.get("REDIS_URL") or os.getenv(
        "REDIS_URL", "redis://redis:6379/0"
    )
    return redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def _token_key(token: str) -> str:
    # Dùng hash để không lưu JWT gốc trong Redis
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"auth:revoked:{token_hash}"


def revoke_token(token: str, payload: dict) -> bool:
    """Thu hồi token đến khi token hết hạn."""
    remaining_seconds = int(payload["exp"]) - int(time.time())

    if remaining_seconds <= 0:
        return False

    client = _get_redis_client()
    client.set(
        _token_key(token),
        "1",
        ex=remaining_seconds,
    )
    return True


def is_token_revoked(token: str) -> bool:
    """Kiểm tra token có nằm trong danh sách thu hồi không."""
    client = _get_redis_client()
    return client.exists(_token_key(token)) == 1
