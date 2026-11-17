from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "mysql+pymysql://test:test@127.0.0.1/agentconnect_test"
os.environ["GEMINI_API_KEY"] = ""
os.environ["SESSION_COOKIE_SECURE"] = "false"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app import models
from app.models.auth_session import AuthSession
from app.models.user import User


@pytest.fixture
def test_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    yield test_session
    engine.dispose()


@pytest.fixture
def app(test_session_factory):
    app = FastAPI()

    def override_get_db():
        with test_session_factory() as db:
            yield db

    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture
def authenticate_as(test_session_factory):
    def authenticate(client, email):
        subject = f"test-{secrets.token_urlsafe(12)}"
        raw_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        with test_session_factory() as db:
            user = User(
                issuer="https://accounts.google.com",
                subject=subject,
                email=email,
                email_verified=True,
                name=email,
            )
            db.add(user)
            db.flush()
            db.add(
                AuthSession(
                    user_id=user.id,
                    token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                    csrf_token_hash=hashlib.sha256(csrf_token.encode()).hexdigest(),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
                )
            )
            db.commit()
        client.cookies.set(settings.session_cookie_name, raw_token)
        client.headers.update(
            {
                "Origin": "http://localhost:5173",
                "X-CSRF-Token": csrf_token,
            }
        )
        return user.id

    return authenticate


@pytest.fixture
def client(app, authenticate_as):
    with TestClient(app) as test_client:
        authenticate_as(test_client, "test@example.com")
        yield test_client


@pytest.fixture
def unauthenticated_client(app):
    with TestClient(app) as test_client:
        yield test_client
