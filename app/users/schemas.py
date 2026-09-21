from pydantic import BaseModel, EmailStr, field_validator
from pydantic_core import PydanticCustomError


class NewUser(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("username", "email", "password", mode="before")
    @classmethod
    def reject_blank_string(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            raise PydanticCustomError("blank", "can't be blank")
        return value


class NewUserRequest(BaseModel):
    user: NewUser


class UserPayload(BaseModel):
    username: str
    email: EmailStr
    token: str
    bio: str | None
    image: str | None


class UserResponse(BaseModel):
    user: UserPayload
