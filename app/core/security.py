import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

password_hash = PasswordHash.recommended()
dummy_password_hash = password_hash.hash("NotARealPassword123")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user_id: UUID, settings: Settings) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "jti": str(uuid4()),
        "iss": "onda-api",
        "aud": "onda-ios",
    }
    token = jwt.encode(payload, settings.api_jwt_secret, algorithm=settings.api_jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str, settings: Settings) -> UUID:
    payload = jwt.decode(
        token,
        settings.api_jwt_secret,
        algorithms=[settings.api_jwt_algorithm],
        audience="onda-ios",
        issuer="onda-api",
        options={"require": ["sub", "type", "iat", "nbf", "exp", "jti"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Unexpected token type")
    return UUID(payload["sub"])


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
