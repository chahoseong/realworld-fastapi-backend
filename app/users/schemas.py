from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

Password = Annotated[str, Field(min_length=8)]


class NewUser(BaseModel):
    username: str
    email: EmailStr
    password: Password

    @field_validator("username", "email", "password", mode="before")
    @classmethod
    def reject_blank_string(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            raise PydanticCustomError("blank", "can't be blank")
        return value


class NewUserRequest(BaseModel):
    user: NewUser


class UpdateUser(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    password: Password | None = None
    bio: str | None = None
    image: str | None = None

    @field_validator("username", "email", "password", mode="before")
    @classmethod
    def reject_null_or_blank_string(cls, value: object) -> object:
        if value is None:
            raise PydanticCustomError("null", "can't be null")
        if isinstance(value, str) and value.strip() == "":
            raise PydanticCustomError("blank", "can't be blank")
        return value

    @field_validator("bio", "image", mode="before")
    @classmethod
    def normalize_empty_string(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def require_field(self) -> UpdateUser:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class UpdateUserRequest(BaseModel):
    user: UpdateUser


class LoginUser(BaseModel):
    email: str
    password: str

    @field_validator("email", "password", mode="before")
    @classmethod
    def reject_blank_string(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            raise PydanticCustomError("blank", "can't be blank")
        return value


class LoginUserRequest(BaseModel):
    user: LoginUser


class UserPayload(BaseModel):
    username: str
    email: EmailStr
    token: str
    bio: str | None
    image: str | None


class UserResponse(BaseModel):
    user: UserPayload


class ProfilePayload(BaseModel):
    username: str
    bio: str | None
    image: str | None
    following: bool


class ProfileResponse(BaseModel):
    profile: ProfilePayload
