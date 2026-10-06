"""Verify Supabase Auth access tokens.

Supabase Auth signs a JWT for every signed-in user. This module checks that a
token is genuine and current, and turns it into an AuthenticatedUser.

Two signing schemes are supported, matching what a Supabase project can use:

  * JWT signing keys (ES256 / RS256). The public keys are published at
    <SUPABASE_URL>/auth/v1/.well-known/jwks.json and fetched on demand.
  * Legacy shared secret (HS256). Set SUPABASE_JWT_SECRET.

The algorithm in the token header only selects WHICH configured key is used.
It can never make the server treat a public key as a shared secret.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

logger = logging.getLogger("subpay.api.auth")

SHARED_SECRET_ALGORITHM = "HS256"
ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256"})

# Supabase's edge caches the JWKS for 10 minutes; do not hold keys longer than that.
JWKS_CACHE_SECONDS = 600
JWKS_TIMEOUT_SECONDS = 5
CLOCK_SKEW_SECONDS = 30


class InvalidTokenError(Exception):
    """The token is missing, malformed, expired, or not from our Supabase project."""


class VerifierUnavailableError(Exception):
    """The token could not be checked because the signing keys could not be fetched."""


@dataclass(frozen=True)
class AuthenticatedUser:
    """Who is making the request. Built only from a verified token."""

    id: UUID
    email: str | None
    # The caller's own token, forwarded to Supabase so Row Level Security applies.
    access_token: str = field(repr=False)
    claims: dict[str, Any] = field(repr=False, default_factory=dict)


class SigningKeyClient(Protocol):
    """The part of PyJWKClient this module relies on (lets tests supply keys)."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class TokenVerifier:
    def __init__(
        self,
        *,
        audience: str = "authenticated",
        issuer: str = "",
        jwt_secret: str = "",
        jwks_url: str = "",
        jwks_client: SigningKeyClient | None = None,
    ) -> None:
        self._audience = audience
        self._issuer = issuer
        self._jwt_secret = jwt_secret
        if jwks_client is None and jwks_url:
            jwks_client = PyJWKClient(
                jwks_url,
                cache_jwk_set=True,
                lifespan=JWKS_CACHE_SECONDS,
                timeout=JWKS_TIMEOUT_SECONDS,
            )
        self._jwks_client = jwks_client

    @property
    def is_configured(self) -> bool:
        return bool(self._jwt_secret or self._jwks_client)

    def verify(self, token: str) -> AuthenticatedUser:
        """Return the user for a valid token. Raise InvalidTokenError otherwise."""
        algorithm, key = self._resolve_key(token)

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer or None,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(str(exc)) from exc

        # API keys and service tokens are not signed-in users.
        if claims.get("role") != "authenticated":
            raise InvalidTokenError("Token is not a signed-in user token")

        try:
            user_id = UUID(str(claims["sub"]))
        except ValueError as exc:
            raise InvalidTokenError("Token subject is not a user id") from exc

        email = claims.get("email")
        return AuthenticatedUser(
            id=user_id,
            email=email if isinstance(email, str) and email else None,
            access_token=token,
            claims=claims,
        )

    def _resolve_key(self, token: str) -> tuple[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("Malformed token") from exc

        algorithm = header.get("alg")

        if algorithm == SHARED_SECRET_ALGORITHM:
            if not self._jwt_secret:
                raise InvalidTokenError("HS256 tokens are not accepted by this server")
            return algorithm, self._jwt_secret

        if algorithm in ASYMMETRIC_ALGORITHMS:
            if self._jwks_client is None:
                raise InvalidTokenError(f"{algorithm} tokens are not accepted by this server")
            try:
                return algorithm, self._jwks_client.get_signing_key_from_jwt(token).key
            except PyJWKClientConnectionError as exc:
                logger.error("Could not fetch Supabase signing keys: %s", exc)
                raise VerifierUnavailableError(str(exc)) from exc
            except (PyJWKClientError, jwt.PyJWTError) as exc:
                raise InvalidTokenError("Unknown signing key") from exc

        raise InvalidTokenError("Unsupported token algorithm")
