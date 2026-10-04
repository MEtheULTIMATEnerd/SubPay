"""Authentication protection: who gets in, who is rejected, and where identity comes from."""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError

from app.api.deps import get_token_verifier
from app.core.security import InvalidTokenError, TokenVerifier
from tests.conftest import HS_SECRET, ISSUER, USER_ID, StaticKeyClient, new_user_id

WHOAMI = "/api/v1/_test/whoami"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_unauthenticated(response: Any) -> None:
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["www-authenticate"] == "Bearer"


# ---- accepted -----------------------------------------------------------------


def test_valid_es256_token_is_accepted(client: TestClient, make_token: Callable[..., str]) -> None:
    response = client.get(WHOAMI, headers=bearer(make_token()))
    assert response.status_code == 200
    assert response.json() == {"id": USER_ID, "email": "owner.a@subpay.test"}


def test_valid_legacy_hs256_token_is_accepted(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    response = client.get(WHOAMI, headers=bearer(make_token(algorithm="HS256")))
    assert response.status_code == 200
    assert response.json()["id"] == USER_ID


def test_identity_comes_from_the_token_not_the_request(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    someone_else = new_user_id()
    response = client.get(
        WHOAMI,
        params={"user_id": someone_else, "organisation_id": new_user_id()},
        headers=bearer(make_token()),
    )
    assert response.status_code == 200
    assert response.json()["id"] == USER_ID


# ---- rejected -----------------------------------------------------------------


def test_missing_authorization_header_is_rejected(client: TestClient) -> None:
    assert_unauthenticated(client.get(WHOAMI))


def test_non_bearer_scheme_is_rejected(client: TestClient) -> None:
    assert_unauthenticated(client.get(WHOAMI, headers={"Authorization": "Basic dXNlcjpwYXNz"}))


def test_garbage_token_is_rejected(client: TestClient) -> None:
    assert_unauthenticated(client.get(WHOAMI, headers=bearer("not-a-jwt")))


def test_expired_token_is_rejected(client: TestClient, make_token: Callable[..., str]) -> None:
    token = make_token(exp=int(time.time()) - 3600)
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(token)))


def test_token_without_expiry_is_rejected(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(make_token(exp=None))))


def test_token_signed_by_an_untrusted_key_is_rejected(
    client: TestClient, make_token: Callable[..., str], other_ec_private_key: Any
) -> None:
    token = make_token(key=other_ec_private_key)
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(token)))


def test_token_signed_with_the_wrong_shared_secret_is_rejected(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    token = make_token(algorithm="HS256", key="a-different-secret-that-is-also-32-bytes-long")
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(token)))


def test_wrong_audience_is_rejected(client: TestClient, make_token: Callable[..., str]) -> None:
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(make_token(aud="some-other-app"))))


def test_token_from_another_supabase_project_is_rejected(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    token = make_token(iss="https://another-project.supabase.co/auth/v1")
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(token)))


def test_anon_api_key_is_not_a_user(client: TestClient, make_token: Callable[..., str]) -> None:
    """Supabase's legacy anon key is a validly signed JWT with role=anon and no subject."""
    token = make_token(algorithm="HS256", role="anon", sub=None, email=None)
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(token)))


def test_service_role_token_is_not_a_user(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    token = make_token(algorithm="HS256", role="service_role")
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(token)))


def test_subject_must_be_a_user_id(client: TestClient, make_token: Callable[..., str]) -> None:
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(make_token(sub="not-a-uuid"))))


def test_unsigned_token_is_rejected(client: TestClient) -> None:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": USER_ID,
            "aud": "authenticated",
            "role": "authenticated",
            "iss": ISSUER,
            "exp": now + 3600,
        },
        key="",
        algorithm="none",
    )
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(token)))


def test_unsupported_algorithm_is_rejected(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    token = make_token(algorithm="HS512", key=HS_SECRET + HS_SECRET)
    assert_unauthenticated(client.get(WHOAMI, headers=bearer(token)))


# ---- verifier configuration ---------------------------------------------------


def test_hs256_is_refused_when_no_shared_secret_is_configured(
    make_token: Callable[..., str], ec_private_key: Any
) -> None:
    """A project on signing keys must not accept shared-secret tokens at all."""
    verifier = TokenVerifier(
        issuer=ISSUER, jwks_client=StaticKeyClient(ec_private_key.public_key())
    )
    with pytest.raises(InvalidTokenError):
        verifier.verify(make_token(algorithm="HS256"))
    assert verifier.verify(make_token()).email == "owner.a@subpay.test"


def test_public_key_cannot_be_used_as_a_shared_secret(ec_private_key: Any) -> None:
    """Algorithm-confusion attack: sign HS256 using the server's PUBLIC key as the secret."""
    public_pem = ec_private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    # Built by hand: PyJWT itself refuses to sign HS256 with a PEM key.
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(
        json.dumps(
            {
                "sub": USER_ID,
                "aud": "authenticated",
                "role": "authenticated",
                "iss": ISSUER,
                "exp": int(time.time()) + 3600,
            }
        ).encode()
    )
    signature = b64(hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    forged = f"{header}.{payload}.{signature}"

    # Server on signing keys only (no shared secret).
    keys_only = TokenVerifier(
        issuer=ISSUER, jwks_client=StaticKeyClient(ec_private_key.public_key())
    )
    with pytest.raises(InvalidTokenError):
        keys_only.verify(forged)

    # Server with both configured: HS256 is checked against the secret, never the public key.
    both = TokenVerifier(
        issuer=ISSUER,
        jwt_secret=HS_SECRET,
        jwks_client=StaticKeyClient(ec_private_key.public_key()),
    )
    with pytest.raises(InvalidTokenError):
        both.verify(forged)


def test_unconfigured_verifier_rejects_everything(make_token: Callable[..., str]) -> None:
    verifier = TokenVerifier()
    assert verifier.is_configured is False
    with pytest.raises(InvalidTokenError):
        verifier.verify(make_token())
    with pytest.raises(InvalidTokenError):
        verifier.verify(make_token(algorithm="HS256"))


def test_unreachable_signing_keys_give_503_not_401(
    app: FastAPI, client: TestClient, make_token: Callable[..., str]
) -> None:
    """If Supabase's key endpoint is down, do not tell the user their session is invalid."""

    class DownClient:
        def get_signing_key_from_jwt(self, token: str) -> Any:
            raise PyJWKClientConnectionError("connection refused")

    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        issuer=ISSUER, jwks_client=DownClient()
    )
    response = client.get(WHOAMI, headers=bearer(make_token()))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
