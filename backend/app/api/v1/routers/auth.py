import secrets
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.auth import (
    CurrentPrincipal,
    CsrfProtectedPrincipal,
    DbSession,
    hash_token,
)
from app.core.config import settings
from app.schemas.auth import CsrfTokenRead, UserRead
from app.services.auth_service import (
    InvalidIdentityToken,
    InvalidOAuthTransaction,
    OAuthConfigurationError,
    OAuthProviderError,
    begin_google_login,
    consume_google_transaction,
    create_auth_session,
    exchange_authorization_code,
    get_or_create_user,
    verify_google_id_token,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _set_auth_cookie(response: Response, token: str, *, max_age: int) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def _clear_oauth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.oauth_transaction_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )


def _auth_error_redirect(error_code: str) -> RedirectResponse:
    frontend = urlsplit(settings.frontend_base_url)
    query = [
        (key, value)
        for key, value in parse_qsl(frontend.query, keep_blank_values=True)
        if key != "auth_error"
    ]
    query.append(("auth_error", error_code))
    location = urlunsplit(
        (
            frontend.scheme,
            frontend.netloc,
            frontend.path,
            urlencode(query),
            frontend.fragment,
        )
    )
    response = RedirectResponse(location, status_code=status.HTTP_303_SEE_OTHER)
    _clear_oauth_cookie(response)
    return response


@router.get("/google/login", summary="Start Google sign-in")
def google_login(db: DbSession) -> Response:
    try:
        authorization_url, browser_binding = begin_google_login(db)
    except OAuthConfigurationError as exc:
        return _auth_error_redirect("signin_unavailable")

    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=settings.oauth_transaction_cookie_name,
        value=browser_binding,
        max_age=settings.oauth_transaction_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/callback", summary="Complete Google sign-in")
def google_callback(
    request: Request,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    browser_binding = request.cookies.get(settings.oauth_transaction_cookie_name)
    if error:
        return _auth_error_redirect(
            "signin_cancelled" if error == "access_denied" else "provider_unavailable"
        )
    if not code or not state or not browser_binding:
        return _auth_error_redirect("signin_failed")

    try:
        transaction, code_verifier = consume_google_transaction(
            db,
            state=state,
            browser_binding=browser_binding,
        )
        id_token = exchange_authorization_code(
            code=code,
            code_verifier=code_verifier,
        )
        claims = verify_google_id_token(
            id_token,
            expected_nonce=transaction.nonce,
        )
        user = get_or_create_user(db, claims)
        raw_session_token, _, _ = create_auth_session(db, user)
    except InvalidOAuthTransaction:
        return _auth_error_redirect("signin_failed")
    except InvalidIdentityToken:
        return _auth_error_redirect("identity_failed")
    except OAuthConfigurationError:
        return _auth_error_redirect("signin_unavailable")
    except OAuthProviderError:
        return _auth_error_redirect("provider_unavailable")

    response = RedirectResponse(
        settings.frontend_base_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _set_auth_cookie(
        response,
        raw_session_token,
        max_age=settings.session_ttl_seconds,
    )
    _clear_oauth_cookie(response)
    return response


@router.get("/session", response_model=UserRead, summary="Get the current user")
def current_session(principal: CurrentPrincipal) -> UserRead:
    return principal.user


@router.get(
    "/csrf",
    response_model=CsrfTokenRead,
    summary="Get a CSRF token for the current session",
)
def csrf_token(
    db: DbSession,
    principal: CurrentPrincipal,
) -> CsrfTokenRead:
    token = secrets.token_urlsafe(32)
    principal.session.csrf_token_hash = hash_token(token)
    db.commit()
    return CsrfTokenRead(csrf_token=token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current session",
)
def logout(
    db: DbSession,
    principal: CsrfProtectedPrincipal,
) -> Response:
    principal.session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )
    return response
