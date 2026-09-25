from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError


class NewArticle(BaseModel):
    title: str
    description: str
    body: str
    tagList: list[str] = Field(default_factory=list)

    @field_validator("title", "description", "body", mode="before")
    @classmethod
    def reject_blank_string(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            raise PydanticCustomError("blank", "can't be blank")
        return value


class NewArticleRequest(BaseModel):
    article: NewArticle


class UpdateArticle(BaseModel):
    title: str | None = None
    description: str | None = None
    body: str | None = None
    tagList: list[str] | None = None

    @field_validator("title", "description", "body", "tagList", mode="before")
    @classmethod
    def reject_null_or_blank(cls, value: object) -> object:
        if value is None:
            raise PydanticCustomError("null", "can't be null")
        if isinstance(value, str) and value.strip() == "":
            raise PydanticCustomError("blank", "can't be blank")
        return value


class UpdateArticleRequest(BaseModel):
    article: UpdateArticle


class ArticleAuthor(BaseModel):
    username: str
    bio: str | None
    image: str | None
    following: bool


class ArticlePayload(BaseModel):
    slug: str
    title: str
    description: str
    body: str
    tagList: list[str]
    createdAt: datetime
    updatedAt: datetime
    favorited: bool
    favoritesCount: int
    author: ArticleAuthor


class ArticleResponse(BaseModel):
    article: ArticlePayload


class TagsResponse(BaseModel):
    tags: list[str]
