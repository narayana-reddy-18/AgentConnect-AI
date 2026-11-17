from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.notification import Notification


class NotificationNotFoundError(Exception):
    pass


def list_notifications(
    db: Session,
    *,
    owner_user_id: int,
    agent_id: int,
    unread_only: bool,
    limit: int,
    offset: int,
) -> list[Notification]:
    if db.scalar(
        select(Agent.id).where(
            Agent.id == agent_id,
            Agent.owner_user_id == owner_user_id,
        )
    ) is None:
        raise NotificationNotFoundError

    statement = (
        select(Notification)
        .join(Agent, Agent.id == Notification.agent_id)
        .where(
            Notification.agent_id == agent_id,
            Agent.owner_user_id == owner_user_id,
        )
    )
    if unread_only:
        statement = statement.where(Notification.is_read.is_(False))
    statement = (
        statement.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).all())


def mark_notification_read(
    db: Session,
    *,
    notification_id: int,
    agent_id: int,
    owner_user_id: int,
) -> Notification:
    notification = db.scalar(
        select(Notification)
        .join(Agent, Agent.id == Notification.agent_id)
        .where(
            Notification.id == notification_id,
            Notification.agent_id == agent_id,
            Agent.owner_user_id == owner_user_id,
        )
    )
    if notification is None:
        raise NotificationNotFoundError

    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification
