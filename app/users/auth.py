from typing import Annotated

import jwt
from fastapi import Depends, status
from fastapi.security import APIKeyHeader

from app.config import get_settings
from app.database import SessionDep
from app.errors import ApiError
from app.security import decode_access_token
from app.users.models import User

token_header = APIKeyHeader(
    name="Authorization",
    scheme_name="Token",
    auto_error=False,
)


def _invalid_token() -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, {"token": ["is invalid"]})


def authenticate_user(
    session: SessionDep,
    authorization: Annotated[str | None, Depends(token_header)],
) -> tuple[User, str]:
    if authorization is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, {"token": ["is missing"]})

    scheme, separator, token = authorization.partition(" ")
    if scheme != "Token" or not separator or not token or token != token.strip():
        raise _invalid_token()

    secret_key = get_settings().jwt_secret_key.get_secret_value()
    try:
        claims = decode_access_token(token, secret_key)
    except jwt.InvalidTokenError as exception:
        raise _invalid_token() from exception

    subject = claims.get("sub")
    if (
        not isinstance(subject, str)
        or not subject.isascii()
        or not subject.isdecimal()
        or len(subject) > 19
    ):
        raise _invalid_token()

    user_id = int(subject)
    if user_id < 1 or user_id > 2**63 - 1:
        raise _invalid_token()

    user = session.get(User, user_id)
    if user is None:
        raise _invalid_token()

    return user, token


CurrentUserDep = Annotated[tuple[User, str], Depends(authenticate_user)]
