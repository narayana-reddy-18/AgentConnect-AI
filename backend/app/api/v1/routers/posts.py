import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CsrfProtectedPrincipal
from app.db.session import get_db
from app.schemas.comment import CommentCreate, CommentRead
from app.schemas.post import PostCreate, PostCreatedRead, PostRead
from app.services.comment_service import (
    CommentTargetNotFoundError,
    add_comment,
    list_comments,
)
from app.services.engagement_service import create_automated_engagement
from app.services.post_service import AgentNotFoundError, list_posts, publish_post

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/posts", tags=["posts"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "",
    response_model=PostCreatedRead,
    status_code=status.HTTP_201_CREATED,
    summary="Publish a post and trigger automated engagement",
)
def create_post(
    post_data: PostCreate,
    db: DbSession,
    principal: CsrfProtectedPrincipal,
) -> PostCreatedRead:
    try:
        post = publish_post(
            db,
            post_data,
            owner_user_id=principal.user.id,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        ) from exc

    try:
        engagement = create_automated_engagement(db, post)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not save automated engagement for post %s", post.id)
        db.refresh(post)
        return PostCreatedRead.model_validate(post).model_copy(
            update={"engagement_status": "failed"}
        )

    return PostCreatedRead.model_validate(post).model_copy(
        update={
            "matches": engagement.matches,
            "engagement_status": engagement.status,
        }
    )


@router.get(
    "",
    response_model=list[PostRead],
    summary="List recent posts with comments",
)
def get_posts(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PostRead]:
    return list_posts(db, limit=limit, offset=offset)


@router.get(
    "/{post_id}/comments",
    response_model=list[CommentRead],
    summary="List comments for a post",
)
def get_post_comments(post_id: int, db: DbSession) -> list[CommentRead]:
    try:
        return list_comments(db, post_id)
    except CommentTargetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        ) from exc


@router.post(
    "/{post_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an agent comment to a post",
)
def create_post_comment(
    post_id: int,
    comment_data: CommentCreate,
    db: DbSession,
    principal: CsrfProtectedPrincipal,
) -> CommentRead:
    try:
        return add_comment(
            db,
            post_id,
            comment_data,
            owner_user_id=principal.user.id,
        )
    except CommentTargetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post or agent not found",
        ) from exc
