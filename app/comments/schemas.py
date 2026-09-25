from datetime import datetime

from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

from app.users.schemas import ProfilePayload


class NewComment(BaseModel):
    body: str

    @field_validator("body", mode="before")
    @classmethod
    def reject_blank_string(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            raise PydanticCustomError("blank", "can't be blank")
        return value


class NewCommentRequest(BaseModel):
    comment: NewComment


class CommentPayload(BaseModel):
    id: int
    body: str
    createdAt: datetime
    updatedAt: datetime
    author: ProfilePayload


class CommentResponse(BaseModel):
    comment: CommentPayload


class CommentsResponse(BaseModel):
    comments: list[CommentPayload]
