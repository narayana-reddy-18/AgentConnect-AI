from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommentCreate(BaseModel):
    agent_id: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Comment must not be blank")
        return value


class CommentRead(BaseModel):
    id: int
    post_id: int
    agent_id: int
    content: str
    source: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
