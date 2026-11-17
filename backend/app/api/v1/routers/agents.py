from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import CurrentPrincipal, CsrfProtectedPrincipal
from app.db.session import get_db
from app.schemas.agent import AgentCreate, AgentRead
from app.services.agent_service import (
    DuplicateAgentEmailError,
    list_agents,
    list_owned_agents,
    register_agent,
)

router = APIRouter(prefix="/agents", tags=["agents"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register an agent",
)
def create_agent(
    agent_data: AgentCreate,
    db: DbSession,
    principal: CsrfProtectedPrincipal,
) -> AgentRead:
    try:
        return register_agent(
            db,
            agent_data,
            owner_user_id=principal.user.id,
        )
    except DuplicateAgentEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An agent with this email is already registered",
        ) from exc


@router.get("", response_model=list[AgentRead], summary="List registered agents")
def get_agents(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentRead]:
    return list_agents(db, limit=limit, offset=offset)


@router.get(
    "/mine",
    response_model=list[AgentRead],
    summary="List agents owned by the current user",
)
def get_my_agents(
    db: DbSession,
    principal: CurrentPrincipal,
) -> list[AgentRead]:
    return list_owned_agents(db, owner_user_id=principal.user.id)
