from __future__ import annotations

import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

import httpx
import requests
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.requests_client import OAuth2Session
from cryptography.fernet import Fernet, InvalidToken
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import hash_token
from app.core.config import settings
from app.models.auth_session import AuthSession
from app.models.oauth_transaction import OAuthTransaction
from app.models.user import User

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


class OAuthConfigurationError(Exception):
    pass


class InvalidOAuthTransaction(Exception):
    pass


class OAuthProviderError(Exception):
    pass


class InvalidIdentityToken(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _encrypt_code_verifier(code_verifier: str) -> str:
    key = settings.oauth_transaction_encryption_key
    if key is None:
        raise OAuthConfigurationError
    try:
        return Fernet(key.get_secret_value().encode("ascii")).encrypt(
            code_verifier.encode("ascii")
        ).decode("ascii")
    except (ValueError, TypeError) as exc:
        raise OAuthConfigurationError from exc


def _decrypt_code_verifier(encrypted: str) -> str:
    key = settings.oauth_transaction_encryption_key
    if key is None:
        raise OAuthConfigurationError
    try:
        return Fernet(key.get_secret_value().encode("ascii")).decrypt(
            encrypted.encode("ascii")
        ).decode("ascii")
    except (InvalidToken, ValueError, TypeError, UnicodeError) as exc:
        raise InvalidOAuthTransaction from exc


def begin_google_login(db: Session) -> tuple[str, str]:
    if (
        not settings.google_client_id
        or settings.google_client_secret is None
        or not settings.google_client_secret.get_secret_value().strip()
    ):
        raise OAuthConfigurationError

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    browser_binding = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(48)
    now = _now()

    db.add(
        OAuthTransaction(
            state_hash=hash_token(state),
            browser_binding_hash=hash_token(browser_binding),
            nonce=nonce,
            code_verifier_encrypted=_encrypt_code_verifier(code_verifier),
            expires_at=now + timedelta(seconds=settings.oauth_transaction_ttl_seconds),
        )
    )
    db.commit()

    oauth_client = OAuth2Session(
        settings.google_client_id,
        scope="openid email profile",
        redirect_uri=settings.google_redirect_uri,
        default_timeout=10.0,
    )
    oauth_client.code_challenge_method = "S256"
    authorization_url, _ = oauth_client.create_authorization_url(
        GOOGLE_AUTHORIZATION_ENDPOINT,
        state=state,
        code_verifier=code_verifier,
        nonce=nonce,
    )
    return authorization_url, browser_binding


def consume_google_transaction(
    db: Session,
    *,
    state: str,
    browser_binding: str,
) -> tuple[OAuthTransaction, str]:
    now = _now()
    transaction = db.scalar(
        select(OAuthTransaction).where(
            OAuthTransaction.state_hash == hash_token(state),
        )
    )
    if (
        transaction is None
        or transaction.consumed_at is not None
        or _as_utc(transaction.expires_at) <= now
        or not hmac.compare_digest(
            transaction.browser_binding_hash,
            hash_token(browser_binding),
        )
    ):
        raise InvalidOAuthTransaction

    result = db.execute(
        update(OAuthTransaction)
        .where(
            OAuthTransaction.id == transaction.id,
            OAuthTransaction.consumed_at.is_(None),
            OAuthTransaction.expires_at > now,
        )
        .execution_options(synchronize_session=False)
        .values(consumed_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        raise InvalidOAuthTransaction
    db.commit()
    return transaction, _decrypt_code_verifier(transaction.code_verifier_encrypted)


def exchange_authorization_code(*, code: str, code_verifier: str) -> str:
    if (
        not settings.google_client_id
        or settings.google_client_secret is None
        or not settings.google_client_secret.get_secret_value().strip()
    ):
        raise OAuthConfigurationError
    try:
        oauth_client = OAuth2Session(
            settings.google_client_id,
            settings.google_client_secret.get_secret_value(),
            token_endpoint_auth_method="client_secret_post",
            scope="openid email profile",
            redirect_uri=settings.google_redirect_uri,
            default_timeout=10.0,
        )
        token = oauth_client.fetch_token(
            url=GOOGLE_TOKEN_ENDPOINT,
            grant_type="authorization_code",
            code=code,
            code_verifier=code_verifier,
        )
    except (OAuthError, requests.RequestException, ValueError) as exc:
        raise OAuthProviderError from exc

    id_token = token.get("id_token") if isinstance(token, dict) else None
    if not isinstance(id_token, str) or not id_token:
        raise OAuthProviderError
    return id_token


def verify_google_id_token(id_token: str, *, expected_nonce: str) -> dict[str, object]:
    if not settings.google_client_id:
        raise OAuthConfigurationError

    try:
        response = httpx.get(GOOGLE_JWKS_ENDPOINT, timeout=10.0)
        response.raise_for_status()
        key_set = KeySet.import_key_set(response.json())
        token = jwt.decode(
            id_token,
            key_set,
            algorithms=["RS256"],
        )
        claims = token.claims
        JWTClaimsRegistry(
            leeway=60,
            iss={"essential": True, "values": sorted(GOOGLE_ISSUERS)},
            aud={"essential": True, "value": settings.google_client_id},
            exp={"essential": True},
            iat={"essential": True},
            sub={"essential": True},
            nonce={"essential": True},
        ).validate(claims)
    except httpx.HTTPError as exc:
        raise OAuthProviderError from exc
    except (JoseError, ValueError, TypeError, KeyError) as exc:
        raise InvalidIdentityToken from exc

    if not hmac.compare_digest(str(claims.get("nonce", "")), expected_nonce):
        raise InvalidIdentityToken
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if settings.google_client_id not in audiences:
        raise InvalidIdentityToken
    if len(audiences) > 1 and claims.get("azp") != settings.google_client_id:
        raise InvalidIdentityToken
    if claims.get("email_verified") is not True:
        raise InvalidIdentityToken
    subject = claims.get("sub")
    email = claims.get("email")
    issuer = claims.get("iss")
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(email, str)
        or not email
        or issuer not in GOOGLE_ISSUERS
        or int(claims.get("iat", 0)) > time.time() + 60
    ):
        raise InvalidIdentityToken
    return dict(claims)


def get_or_create_user(db: Session, claims: dict[str, object]) -> User:
    issuer = str(claims["iss"])
    subject = str(claims["sub"])
    user = db.scalar(
        select(User).where(User.issuer == issuer, User.subject == subject)
    )
    if user is not None:
        user.email = str(claims["email"])
        user.email_verified = claims.get("email_verified") is True
        user.name = str(claims["name"]) if claims.get("name") else None
        db.commit()
        db.refresh(user)
        return user

    user = User(
        issuer=issuer,
        subject=subject,
        email=str(claims["email"]),
        email_verified=claims.get("email_verified") is True,
        name=str(claims["name"]) if claims.get("name") else None,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        user = db.scalar(
            select(User).where(User.issuer == issuer, User.subject == subject)
        )
        if user is None:
            raise
        return user
    db.refresh(user)
    return user


def create_auth_session(db: Session, user: User) -> tuple[str, str, AuthSession]:
    raw_session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(raw_session_token),
        csrf_token_hash=hash_token(csrf_token),
        expires_at=_now() + timedelta(seconds=settings.session_ttl_seconds),
    )
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    return raw_session_token, csrf_token, auth_session
