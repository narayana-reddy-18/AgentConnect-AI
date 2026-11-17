from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.auth_session import AuthSession
from app.models.user import User


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user: User
    session: AuthSession


DbSession = Annotated[Session, Depends(get_db)]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_current_principal(request: Request, db: DbSession) -> AuthenticatedPrincipal:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
        )
    )
    if auth_session is None or _as_utc(auth_session.expires_at) <= datetime.now(
        timezone.utc
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user = db.get(User, auth_session.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return AuthenticatedPrincipal(user=user, session=auth_session)


CurrentPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(get_current_principal),
]


def require_csrf(
    request: Request,
    principal: CurrentPrincipal,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthenticatedPrincipal:
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in settings.csrf_trusted_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not trusted",
        )

    if not csrf_token or not hmac.compare_digest(
        hash_token(csrf_token),
        principal.session.csrf_token_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Valid CSRF token required",
        )
    return principal


CsrfProtectedPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(require_csrf),
]
