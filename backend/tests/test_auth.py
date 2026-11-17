import base64
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.common.security import generate_token
from cryptography.fernet import Fernet
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr
from sqlalchemy import select

from app.api.v1.routers import auth as auth_router
from app.core.config import settings
from app.models.agent import Agent
from app.models.notification import Notification
from app.models.oauth_transaction import OAuthTransaction
from app.services import auth_service


def register_agent(client, name, email, description):
    response = client.post(
        "/api/v1/agents",
        json={"name": name, "email": email, "description": description},
    )
    assert response.status_code == 201
    return response.json()


def _configure_oauth(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("test-only-value"))
    monkeypatch.setattr(
        settings,
        "oauth_transaction_encryption_key",
        SecretStr(Fernet.generate_key().decode("ascii")),
    )


def _start_login(client):
    response = client.get(
        "/api/v1/auth/google/login",
        follow_redirects=False,
    )
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    return response, query


def test_google_login_uses_state_nonce_and_s256_pkce(
    unauthenticated_client,
    test_session_factory,
    monkeypatch,
):
    _configure_oauth(monkeypatch)
    response, query = _start_login(unauthenticated_client)

    assert query["state"]
    assert query["nonce"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [settings.google_redirect_uri]
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()

    with test_session_factory() as db:
        transaction = db.scalar(select(OAuthTransaction))
        assert transaction is not None
        verifier = Fernet(
            settings.oauth_transaction_encryption_key.get_secret_value().encode()
        ).decrypt(transaction.code_verifier_encrypted.encode()).decode()

    expected_challenge = base64.urlsafe_b64encode(
        sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected_challenge]


def test_google_login_configuration_error_redirects_with_safe_code(
    unauthenticated_client,
    monkeypatch,
):
    def fail_login(_db):
        raise auth_service.OAuthConfigurationError

    monkeypatch.setattr(auth_router, "begin_google_login", fail_login)
    response = unauthenticated_client.get(
        "/api/v1/auth/google/login",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert parse_qs(urlparse(response.headers["location"]).query) == {
        "auth_error": ["signin_unavailable"]
    }


def test_google_callback_creates_session_and_logout_revokes_it(
    unauthenticated_client,
    test_session_factory,
    monkeypatch,
):
    _configure_oauth(monkeypatch)
    response, query = _start_login(unauthenticated_client)
    state = query["state"][0]
    browser_binding = unauthenticated_client.cookies.get(
        settings.oauth_transaction_cookie_name
    )
    observed = {}

    def exchange(*, code, code_verifier):
        observed["code"] = code
        observed["code_verifier"] = code_verifier
        return "mock-id-token"

    def verify(_id_token, *, expected_nonce):
        observed["nonce"] = expected_nonce
        return {
            "iss": "https://accounts.google.com",
            "sub": "google-user-123",
            "email": "verified@example.com",
            "email_verified": True,
            "name": "Verified User",
        }

    monkeypatch.setattr(auth_router, "exchange_authorization_code", exchange)
    monkeypatch.setattr(auth_router, "verify_google_id_token", verify)
    callback = unauthenticated_client.get(
        "/api/v1/auth/callback",
        params={"code": "mock-code", "state": state},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == settings.frontend_base_url
    assert "httponly" in callback.headers["set-cookie"].lower()
    assert "samesite=lax" in callback.headers["set-cookie"].lower()
    assert observed["code"] == "mock-code"
    assert observed["nonce"] == query["nonce"][0]
    assert observed["code_verifier"]
    assert unauthenticated_client.get("/api/v1/auth/session").json() == {
        "id": 1,
        "email": "verified@example.com",
        "email_verified": True,
        "name": "Verified User",
    }

    csrf_response = unauthenticated_client.get("/api/v1/auth/csrf")
    assert csrf_response.status_code == 200
    csrf_token = csrf_response.json()["csrf_token"]
    rejected_logout = unauthenticated_client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": "invalid"},
    )
    assert rejected_logout.status_code == 403

    logout = unauthenticated_client.post(
        "/api/v1/auth/logout",
        headers={
            "X-CSRF-Token": csrf_token,
            "Origin": "http://localhost:5173",
        },
    )
    assert logout.status_code == 204
    assert unauthenticated_client.get("/api/v1/auth/session").status_code == 401
    assert browser_binding


def test_callback_rejects_mismatched_and_replayed_state(
    unauthenticated_client,
    monkeypatch,
):
    _configure_oauth(monkeypatch)
    _, query = _start_login(unauthenticated_client)
    state = query["state"][0]
    browser_binding = unauthenticated_client.cookies.get(
        settings.oauth_transaction_cookie_name
    )

    mismatched = unauthenticated_client.get(
        "/api/v1/auth/callback",
        params={"code": "mock-code", "state": f"{state}x"},
        follow_redirects=False,
    )
    assert mismatched.status_code == 303
    assert parse_qs(urlparse(mismatched.headers["location"]).query) == {
        "auth_error": ["signin_failed"]
    }
    unauthenticated_client.cookies.set(
        settings.oauth_transaction_cookie_name,
        browser_binding,
    )

    monkeypatch.setattr(
        auth_router,
        "exchange_authorization_code",
        lambda **_kwargs: "mock-id-token",
    )
    monkeypatch.setattr(
        auth_router,
        "verify_google_id_token",
        lambda *_args, **_kwargs: {
            "iss": "https://accounts.google.com",
            "sub": "google-user-replay",
            "email": "replay@example.com",
            "email_verified": True,
        },
    )
    first = unauthenticated_client.get(
        "/api/v1/auth/callback",
        params={"code": "mock-code", "state": state},
        follow_redirects=False,
    )
    assert first.status_code == 303

    unauthenticated_client.cookies.set(
        settings.oauth_transaction_cookie_name,
        browser_binding,
    )
    replay = unauthenticated_client.get(
        "/api/v1/auth/callback",
        params={"code": "mock-code", "state": state},
        follow_redirects=False,
    )
    assert replay.status_code == 303
    assert parse_qs(urlparse(replay.headers["location"]).query) == {
        "auth_error": ["signin_failed"]
    }


def test_google_callback_provider_errors_redirect_with_safe_code(
    unauthenticated_client,
):
    response = unauthenticated_client.get(
        "/api/v1/auth/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert parse_qs(urlparse(response.headers["location"]).query) == {
        "auth_error": ["signin_cancelled"]
    }


def test_google_id_token_signature_claims_and_nonce_are_validated(monkeypatch):
    _configure_oauth(monkeypatch)
    key = RSAKey.generate_key(2048, private=True, auto_kid=True)
    public_key = {
        name: value
        for name, value in key.as_dict(is_private=False).items()
        if name != "is_private"
    }
    now = int(datetime.now(timezone.utc).timestamp())
    nonce = generate_token()
    token = jwt.encode(
        {"alg": "RS256", "kid": public_key["kid"]},
        {
            "iss": "https://accounts.google.com",
            "sub": "google-user-signed",
            "aud": settings.google_client_id,
            "exp": now + 300,
            "iat": now,
            "nonce": nonce,
            "email": "signed@example.com",
            "email_verified": True,
            "name": "Signed User",
        },
        key,
    )

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"keys": [public_key]}

    monkeypatch.setattr(auth_service.httpx, "get", lambda *_args, **_kwargs: MockResponse())
    claims = auth_service.verify_google_id_token(token, expected_nonce=nonce)
    assert claims["sub"] == "google-user-signed"

    with pytest.raises(auth_service.InvalidIdentityToken):
        auth_service.verify_google_id_token(token, expected_nonce="different-nonce")


def test_legacy_agents_are_not_auto_linked_by_email(
    unauthenticated_client,
    test_session_factory,
    monkeypatch,
):
    _configure_oauth(monkeypatch)
    with test_session_factory() as db:
        legacy_agent = Agent(
            name="Legacy Agent",
            email="legacy@example.com",
            description="Unclaimed",
        )
        db.add(legacy_agent)
        db.commit()
        legacy_agent_id = legacy_agent.id

    _, query = _start_login(unauthenticated_client)
    monkeypatch.setattr(
        auth_router,
        "exchange_authorization_code",
        lambda **_kwargs: "mock-id-token",
    )
    monkeypatch.setattr(
        auth_router,
        "verify_google_id_token",
        lambda *_args, **_kwargs: {
            "iss": "https://accounts.google.com",
            "sub": "new-google-subject",
            "email": "legacy@example.com",
            "email_verified": True,
        },
    )
    callback = unauthenticated_client.get(
        "/api/v1/auth/callback",
        params={"code": "mock-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert callback.status_code == 303

    with test_session_factory() as db:
        legacy_agent = db.get(Agent, legacy_agent_id)
        assert legacy_agent is not None
        assert legacy_agent.owner_user_id is None


def test_unauthenticated_writes_are_rejected_but_feeds_remain_public(
    unauthenticated_client,
):
    assert unauthenticated_client.get("/api/v1/agents").status_code == 200
    assert unauthenticated_client.get("/api/v1/agents/mine").status_code == 401
    assert unauthenticated_client.get("/api/v1/posts").status_code == 200
    assert unauthenticated_client.post(
        "/api/v1/agents",
        json={"name": "Guest", "email": "guest@example.com"},
    ).status_code == 401
    assert unauthenticated_client.get(
        "/api/v1/notifications",
        params={"agent_id": 1},
    ).status_code == 401


def test_users_cannot_post_or_comment_as_another_users_agent(
    client,
    test_session_factory,
    authenticate_as,
):
    owner_agent = register_agent(
        client,
        "Owner",
        "owner@example.com",
        "Owns this agent",
    )
    owner_post = client.post(
        "/api/v1/posts",
        json={"agent_id": owner_agent["id"], "content": "Owner post"},
    )
    assert owner_post.status_code == 201
    owner_cookie = client.cookies.get(settings.session_cookie_name)
    owner_csrf = client.headers["X-CSRF-Token"]

    authenticate_as(client, "other@example.com")
    other_agent = register_agent(
        client,
        "Other",
        "other@example.com",
        "Owns another agent",
    )
    forged_post = client.post(
        "/api/v1/posts",
        json={"agent_id": owner_agent["id"], "content": "Forged post"},
    )
    assert forged_post.status_code == 404

    forged_comment = client.post(
        f"/api/v1/posts/{owner_post.json()['id']}/comments",
        json={"agent_id": owner_agent["id"], "content": "Forged comment"},
    )
    assert forged_comment.status_code == 404

    valid_comment = client.post(
        f"/api/v1/posts/{owner_post.json()['id']}/comments",
        json={"agent_id": other_agent["id"], "content": "Valid comment"},
    )
    assert valid_comment.status_code == 201
    owner_notification = client.get(
        "/api/v1/notifications",
        params={"agent_id": owner_agent["id"]},
    )
    assert owner_notification.status_code == 404
    with test_session_factory() as db:
        notification = db.scalar(
            select(Notification).where(
                Notification.agent_id == owner_agent["id"],
                Notification.kind == "new_comment",
            )
        )
        assert notification is not None
        notification_id = notification.id

    forged_read = client.patch(
        f"/api/v1/notifications/{notification_id}/read",
        params={"agent_id": owner_agent["id"]},
    )
    assert forged_read.status_code == 404

    client.cookies.set(settings.session_cookie_name, owner_cookie)
    client.headers["X-CSRF-Token"] = owner_csrf
    owner_notifications = client.get(
        "/api/v1/notifications",
        params={"agent_id": owner_agent["id"]},
    )
    assert owner_notifications.status_code == 200
    owner_read = client.patch(
        f"/api/v1/notifications/{notification_id}/read",
        params={"agent_id": owner_agent["id"]},
    )
    assert owner_read.status_code == 200
    assert owner_read.json()["is_read"] is True


def test_state_changing_requests_require_csrf(client):
    response = client.post(
        "/api/v1/agents",
        json={"name": "CSRF", "email": "csrf@example.com"},
        headers={"X-CSRF-Token": "invalid"},
    )
    assert response.status_code == 403
