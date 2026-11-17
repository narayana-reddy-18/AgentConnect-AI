from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.schemas.agent import AgentCreate


class DuplicateAgentEmailError(Exception):
    pass


def register_agent(
    db: Session,
    agent_data: AgentCreate,
    *,
    owner_user_id: int,
) -> Agent:
    agent = Agent(**agent_data.model_dump(), owner_user_id=owner_user_id)
    db.add(agent)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_duplicate_email_error(exc):
            raise DuplicateAgentEmailError from exc
        raise

    db.refresh(agent)
    return agent


def _is_duplicate_email_error(exc: IntegrityError) -> bool:
    original = exc.orig
    error_code = original.args[0] if original.args else None
    if error_code == 1062:
        return True

    return "unique constraint failed: agents.email" in str(original).lower()


def list_agents(db: Session, *, limit: int, offset: int) -> list[Agent]:
    statement = select(Agent).order_by(Agent.id).limit(limit).offset(offset)
    return list(db.scalars(statement).all())


def list_owned_agents(db: Session, *, owner_user_id: int) -> list[Agent]:
    statement = (
        select(Agent)
        .where(Agent.owner_user_id == owner_user_id)
        .order_by(Agent.id)
    )
    return list(db.scalars(statement).all())
