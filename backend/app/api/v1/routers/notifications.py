from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import CurrentPrincipal, CsrfProtectedPrincipal
from app.db.session import get_db
from app.schemas.notification import NotificationRead
from app.services.notification_service import (
    NotificationNotFoundError,
    list_notifications,
    mark_notification_read,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get(
    "",
    response_model=list[NotificationRead],
    summary="List an agent's in-app notifications",
    description="Returns notifications only for an agent owned by the authenticated user.",
)
def get_notifications(
    db: DbSession,
    principal: CurrentPrincipal,
    agent_id: Annotated[int, Query(gt=0)],
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NotificationRead]:
    try:
        return list_notifications(
            db,
            owner_user_id=principal.user.id,
            agent_id=agent_id,
            unread_only=unread_only,
            limit=limit,
            offset=offset,
        )
    except NotificationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notifications not found for this user",
        ) from exc


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark an agent notification as read",
    description="Updates a notification only when its agent is owned by the authenticated user.",
)
def read_notification(
    notification_id: int,
    db: DbSession,
    principal: CsrfProtectedPrincipal,
    agent_id: Annotated[int, Query(gt=0)],
) -> NotificationRead:
    try:
        return mark_notification_read(
            db,
            notification_id=notification_id,
            agent_id=agent_id,
            owner_user_id=principal.user.id,
        )
    except NotificationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found for this agent",
        ) from exc
