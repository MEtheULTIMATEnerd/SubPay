"""Shared FastAPI dependencies.

Use CurrentUser on every endpoint that needs a signed-in user:

    @router.get("/projects")
    def list_projects(user: CurrentUser): ...

Identity always comes from the verified token. Never read a user id or an
organisation id from the request body, path or query string.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core import errors
from app.core.config import Settings, get_settings
from app.core.security import (
    AuthenticatedUser,
    InvalidTokenError,
    TokenVerifier,
    VerifierUnavailableError,
)

_bearer = HTTPBearer(
    auto_error=False,
    description="Supabase Auth access token for the signed-in user.",
)


@lru_cache
def _build_verifier(audience: str, issuer: str, jwt_secret: str, jwks_url: str) -> TokenVerifier:
    return TokenVerifier(
        audience=audience,
        issuer=issuer,
        jwt_secret=jwt_secret,
        jwks_url=jwks_url,
    )


def get_token_verifier(settings: Annotated[Settings, Depends(get_settings)]) -> TokenVerifier:
    # Cached per configuration, so the fetched signing keys are reused across requests.
    return _build_verifier(
        settings.supabase_jwt_audience,
        settings.supabase_jwt_issuer,
        settings.supabase_jwt_secret.get_secret_value(),
        settings.supabase_jwks_url,
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise errors.unauthenticated()
    try:
        return verifier.verify(credentials.credentials)
    except InvalidTokenError as exc:
        raise errors.unauthenticated(
            "Your session is invalid or has expired. Sign in again."
        ) from exc
    except VerifierUnavailableError as exc:
        raise errors.service_unavailable(
            "Sign-in could not be verified right now. Try again shortly."
        ) from exc


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
