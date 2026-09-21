from fastapi import APIRouter, status

from app.config import get_settings
from app.database import SessionDep
from app.security import create_access_token, hash_password
from app.users.models import User
from app.users.schemas import NewUserRequest, UserPayload, UserResponse

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED)
def register_user(request: NewUserRequest, session: SessionDep) -> UserResponse:
    secret_key = get_settings().jwt_secret_key.get_secret_value()
    password_hash = hash_password(request.user.password)

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

    return response
