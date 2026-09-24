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
