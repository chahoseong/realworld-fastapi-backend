from fastapi import APIRouter, status
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionDep
from app.errors import ApiError
from app.security import create_access_token, hash_password
from app.users.models import User
from app.users.schemas import NewUserRequest, UserPayload, UserResponse

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED)
def register_user(request: NewUserRequest, session: SessionDep) -> UserResponse:
    secret_key = get_settings().jwt_secret_key.get_secret_value()
    password_hash = hash_password(request.user.password)

    try:
        with session.begin():
            user = User(
                username=request.user.username,
                email=request.user.email,
                password_hash=password_hash,
            )
            session.add(user)
            session.flush()

            response = UserResponse(
                user=UserPayload(
                    username=user.username,
                    email=user.email,
                    token=create_access_token(user.id, secret_key),
                    bio=user.bio,
                    image=user.image,
                )
            )
    except IntegrityError as exception:
        constraint_name = getattr(
            getattr(exception.orig, "diag", None),
            "constraint_name",
            None,
        )
        if constraint_name == "uq_users_username":
            raise ApiError(
                status.HTTP_409_CONFLICT,
                {"username": ["has already been taken"]},
            ) from exception
        if constraint_name == "uq_users_email":
            raise ApiError(
                status.HTTP_409_CONFLICT,
                {"email": ["has already been taken"]},
            ) from exception
        raise

    return response
