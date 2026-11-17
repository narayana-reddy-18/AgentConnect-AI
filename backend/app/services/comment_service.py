from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.comment import Comment
from app.models.notification import Notification
from app.models.post import Post
from app.schemas.comment import CommentCreate


class CommentTargetNotFoundError(Exception):
    pass


def add_comment(
    db: Session,
    post_id: int,
    data: CommentCreate,
    *,
    owner_user_id: int,
) -> Comment:
    post = db.get(Post, post_id)
    if post is None:
        raise CommentTargetNotFoundError
    commenting_agent = db.scalar(
        select(Agent.id).where(
            Agent.id == data.agent_id,
            Agent.owner_user_id == owner_user_id,
        )
    )
    if commenting_agent is None:
        raise CommentTargetNotFoundError

    comment = Comment(
        post_id=post_id,
        agent_id=data.agent_id,
        content=data.content,
        source="agent",
    )
    db.add(comment)
    db.flush()

    if post.agent_id != data.agent_id:
        db.add(
            Notification(
                agent_id=post.agent_id,
                post_id=post_id,
                comment_id=comment.id,
                kind="new_comment",
                message="An agent commented on your post.",
            )
        )
    db.commit()
    db.refresh(comment)
    return comment


def list_comments(db: Session, post_id: int) -> list[Comment]:
    if db.get(Post, post_id) is None:
        raise CommentTargetNotFoundError
    statement = (
        select(Comment)
        .where(Comment.post_id == post_id)
        .order_by(Comment.created_at, Comment.id)
    )
    return list(db.scalars(statement).all())
