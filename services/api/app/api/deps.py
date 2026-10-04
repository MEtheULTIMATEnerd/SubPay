"""Shared FastAPI dependencies.

Use CurrentUser on every endpoint that needs a signed-in user:

    @router.get("/projects")
    def list_projects(user: CurrentUser): ...

Identity always comes from the verified token. Never read a user id or an
organisation id from the request body, path or query string.
"""

from functools import lru_cache
from typing import Annotated

import httpx2
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.ai.extraction import ExtractionProvider, HttpExtractionProvider, MockExtractionProvider
from app.core import errors
from app.core.config import Settings, get_settings
from app.core.security import (
    AuthenticatedUser,
    InvalidTokenError,
    TokenVerifier,
    VerifierUnavailableError,
)
from app.db.storage import FileStorage, SupabaseStorage
from app.db.supabase import SupabaseRest, build_http_client
from app.repositories.contracts import ContractRepository, SupabaseContractRepository
from app.repositories.platform import PlatformRepository, SupabasePlatformRepository
from app.services.contracts import ContractService

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


@lru_cache
def get_http_client() -> httpx2.Client:
    """One pooled HTTP client for all calls to Supabase."""
    return build_http_client()


def get_supabase_rest(
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    http: Annotated[httpx2.Client, Depends(get_http_client)],
) -> SupabaseRest:
    """Supabase data access as the signed-in user, so Row Level Security applies.

    Use this in your own repositories. It never uses the service-role key.
    """
    return SupabaseRest(
        http,
        base_url=settings.supabase_base_url,
        anon_key=settings.supabase_anon_key,
        access_token=user.access_token,
    )


UserSupabase = Annotated[SupabaseRest, Depends(get_supabase_rest)]


def get_platform_repository(user: CurrentUser, rest: UserSupabase) -> PlatformRepository:
    return SupabasePlatformRepository(rest, user.id)


Platform = Annotated[PlatformRepository, Depends(get_platform_repository)]


def get_file_storage(
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    http: Annotated[httpx2.Client, Depends(get_http_client)],
) -> FileStorage:
    """Supabase Storage as the signed-in user, so the storage policies apply."""
    return SupabaseStorage(
        http,
        base_url=settings.supabase_base_url,
        anon_key=settings.supabase_anon_key,
        access_token=user.access_token,
    )


UserStorage = Annotated[FileStorage, Depends(get_file_storage)]


def get_extraction_provider(
    settings: Annotated[Settings, Depends(get_settings)],
    http: Annotated[httpx2.Client, Depends(get_http_client)],
) -> ExtractionProvider:
    """The AI boundary. "mock" needs no AI service; "http" calls AI_SERVICE_URL."""
    if settings.ai_extraction_provider == "http":
        return HttpExtractionProvider(http, settings.ai_service_url)
    return MockExtractionProvider()


def get_contract_repository(rest: UserSupabase) -> ContractRepository:
    return SupabaseContractRepository(rest)


def get_contract_service(
    repository: Annotated[ContractRepository, Depends(get_contract_repository)],
    storage: UserStorage,
    extractor: Annotated[ExtractionProvider, Depends(get_extraction_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractService:
    return ContractService(
        repository, storage, extractor, signed_url_seconds=settings.signed_url_seconds
    )


Contracts = Annotated[ContractService, Depends(get_contract_service)]
