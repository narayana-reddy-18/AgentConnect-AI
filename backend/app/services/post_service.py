from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.post import Post
from app.schemas.post import PostCreate


class AgentNotFoundError(Exception):
    pass


def publish_post(
    db: Session,
    post_data: PostCreate,
    *,
    owner_user_id: int,
) -> Post:
    agent = db.scalar(
        select(Agent).where(
            Agent.id == post_data.agent_id,
            Agent.owner_user_id == owner_user_id,
        )
    )
    if agent is None:
        raise AgentNotFoundError

    post = Post(**post_data.model_dump())
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def list_posts(db: Session, *, limit: int, offset: int) -> list[Post]:
    statement = (
        select(Post)
        .options(selectinload(Post.comments), selectinload(Post.matches))
        .order_by(Post.created_at.desc(), Post.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).all())
