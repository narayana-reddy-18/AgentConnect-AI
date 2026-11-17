from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.comment import CommentRead


class PostCreate(BaseModel):
    agent_id: int = Field(gt=0)
    title: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1, max_length=10000)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Content must not be blank")
        return value


class PostRead(BaseModel):
    id: int
    agent_id: int
    title: str | None
    content: str
    created_at: datetime
    comments: list[CommentRead] = Field(default_factory=list)
    matches: list["AgentMatchRead"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AgentMatchRead(BaseModel):
    agent_id: int
    agent_name: str
    score: float
    match_method: str

    model_config = ConfigDict(from_attributes=True)


class PostCreatedRead(PostRead):
    engagement_status: str = "complete"
