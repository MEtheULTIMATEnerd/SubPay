"""Shared fixtures.

No test talks to Supabase. Tokens are signed here with throwaway keys, and the
verifier is given those keys directly instead of fetching a JWKS.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.ai.completeness import MockCompletenessProvider
from app.ai.evidence import MockEvidenceProcessor
from app.ai.extraction import MockExtractionProvider
from app.ai.matching import MockMatchingProvider
from app.ai.variations import MockVariationProvider
from app.api.deps import (
    CurrentUser,
    get_completeness_provider,
    get_contract_repository,
    get_evidence_processor,
    get_evidence_repository,
    get_extraction_provider,
    get_file_storage,
    get_invitation_lookup,
    get_matching_provider,
    get_organisation_repository,
    get_platform_repository,
    get_token_verifier,
    get_variation_provider,
)
from app.core import errors
from app.core.config import Settings
from app.core.security import TokenVerifier
from app.main import create_app
from tests.fakes import (
    FakeContractRepository,
    FakeDatabase,
    FakeEvidenceRepository,
    FakeInvitationLookup,
    FakeOrganisationRepository,
    FakePlatformRepository,
    FakeStorage,
)

SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
HS_SECRET = "test-only-shared-secret-with-at-least-32-bytes!"

# Organisation A: an owner and a member.  Organisation B: an owner.
USER_ID = "a0000000-0000-4000-8000-000000000001"
MEMBER_A_ID = "a0000000-0000-4000-8000-000000000002"
USER_B_ID = "b0000000-0000-4000-8000-000000000001"
# Signed in, but the sign-up trigger never created a profile.
NO_PROFILE_ID = "c0000000-0000-4000-8000-000000000001"


class StaticKeyClient:
    """Stands in for PyJWKClient: always answers with one known public key."""

    def __init__(self, public_key: Any) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        class _SigningKey:
            key = self._public_key

        return _SigningKey()


@pytest.fixture(scope="session")
def ec_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="session")
def other_ec_private_key() -> ec.EllipticCurvePrivateKey:
    """A key the server does not trust."""
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        supabase_url=SUPABASE_URL,
        supabase_anon_key="test-anon-key",
        supabase_jwt_secret=HS_SECRET,
        cors_origins="http://localhost:3000, https://app.subpay.test",
    )


@pytest.fixture
def verifier(ec_private_key: ec.EllipticCurvePrivateKey) -> TokenVerifier:
    return TokenVerifier(
        audience="authenticated",
        issuer=ISSUER,
        jwt_secret=HS_SECRET,
        jwks_client=StaticKeyClient(ec_private_key.public_key()),
    )


def base_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": "authenticated",
        "sub": USER_ID,
        "role": "authenticated",
        "email": "owner.a@subpay.test",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


@pytest.fixture
def make_token(ec_private_key: ec.EllipticCurvePrivateKey) -> Callable[..., str]:
    """make_token() -> a valid ES256 user token. Override claims with keyword arguments;
    pass a claim as None to leave it out."""

    def _make(*, algorithm: str = "ES256", key: Any = None, **claim_overrides: Any) -> str:
        if key is None:
            key = HS_SECRET if algorithm == "HS256" else ec_private_key
        return jwt.encode(
            base_claims(**claim_overrides),
            key,
            algorithm=algorithm,
            headers={"kid": "test-key"},
        )

    return _make


class _EchoBody(BaseModel):
    name: str = Field(min_length=1)
    quantity: int


def _test_router() -> APIRouter:
    """Routes that exist only in tests, to exercise the shared plumbing."""
    router = APIRouter(prefix="/_test")

    @router.get("/whoami")
    def whoami(user: CurrentUser) -> dict[str, Any]:
        return {"id": str(user.id), "email": user.email}

    @router.post("/echo")
    def echo(body: _EchoBody) -> dict[str, Any]:
        return body.model_dump()

    @router.get("/missing")
    def missing() -> None:
        raise errors.not_found("Project")

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    return router


@pytest.fixture
def db() -> FakeDatabase:
    """Two organisations: A (owner + member) and B (owner)."""
    database = FakeDatabase()
    org_a = database.add_organisation("Org A Formwork")
    org_b = database.add_organisation("Org B Scaffolding")
    database.add_profile(USER_ID, org_a, "Alex Owner", "owner")
    database.add_profile(MEMBER_A_ID, org_a, "Morgan Member", "member")
    database.add_profile(USER_B_ID, org_b, "Blake Owner", "owner")
    return database


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def extractor() -> MockExtractionProvider:
    """The built-in mock AI. Set `extractor.available = False` to simulate an outage."""
    return MockExtractionProvider()


@pytest.fixture
def processor() -> MockEvidenceProcessor:
    """The built-in mock evidence AI. Set `processor.available = False` to simulate an outage."""
    return MockEvidenceProcessor()


@pytest.fixture
def matching_provider() -> MockMatchingProvider:
    return MockMatchingProvider()


@pytest.fixture
def completeness_provider() -> MockCompletenessProvider:
    return MockCompletenessProvider()


@pytest.fixture
def variation_provider() -> MockVariationProvider:
    return MockVariationProvider()


@pytest.fixture
def app(
    settings: Settings,
    verifier: TokenVerifier,
    db: FakeDatabase,
    storage: FakeStorage,
    extractor: MockExtractionProvider,
    processor: MockEvidenceProcessor,
    matching_provider: MockMatchingProvider,
    completeness_provider: MockCompletenessProvider,
    variation_provider: MockVariationProvider,
) -> FastAPI:
    application = create_app(settings)
    application.include_router(_test_router(), prefix=settings.api_v1_prefix)
    application.dependency_overrides[get_token_verifier] = lambda: verifier

    def platform_for_caller(user: CurrentUser) -> FakePlatformRepository:
        return FakePlatformRepository(db, user.id)

    def contracts_for_caller(user: CurrentUser) -> FakeContractRepository:
        return FakeContractRepository(db, user.id)

    application.dependency_overrides[get_platform_repository] = platform_for_caller
    application.dependency_overrides[get_contract_repository] = contracts_for_caller
    application.dependency_overrides[get_file_storage] = lambda: storage
    application.dependency_overrides[get_extraction_provider] = lambda: extractor

    def evidence_for_caller(user: CurrentUser) -> FakeEvidenceRepository:
        return FakeEvidenceRepository(db, user.id)

    application.dependency_overrides[get_evidence_repository] = evidence_for_caller
    application.dependency_overrides[get_evidence_processor] = lambda: processor
    application.dependency_overrides[get_matching_provider] = lambda: matching_provider
    application.dependency_overrides[get_completeness_provider] = lambda: completeness_provider
    application.dependency_overrides[get_variation_provider] = lambda: variation_provider

    def organisation_for_caller(user: CurrentUser) -> FakeOrganisationRepository:
        return FakeOrganisationRepository(db, user.id)

    application.dependency_overrides[get_organisation_repository] = organisation_for_caller
    application.dependency_overrides[get_invitation_lookup] = lambda: FakeInvitationLookup(db)
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def as_user(make_token: Callable[..., str]) -> Callable[[str], dict[str, str]]:
    """as_user(USER_B_ID) -> Authorization header for that user."""

    def _headers(user_id: str = USER_ID) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(sub=user_id)}"}

    return _headers


def new_user_id() -> str:
    return str(uuid.uuid4())
