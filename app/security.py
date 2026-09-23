from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, encoded_password: str) -> bool:
    return _password_hash.verify(password, encoded_password)


def create_access_token(user_id: int, secret_key: str) -> str:
    issued_at = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": issued_at,
            "exp": issued_at + ACCESS_TOKEN_LIFETIME,
        },
        secret_key,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str, secret_key: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        secret_key,
        algorithms=[JWT_ALGORITHM],
    )
