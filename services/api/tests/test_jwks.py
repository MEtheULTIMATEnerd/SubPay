"""The real key-fetching path: signing keys are read from a JWKS endpoint.

A throwaway HTTP server on localhost plays the part of
<SUPABASE_URL>/auth/v1/.well-known/jwks.json.
"""

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from jwt.algorithms import ECAlgorithm

from app.core.security import InvalidTokenError, TokenVerifier, VerifierUnavailableError
from tests.conftest import ISSUER, USER_ID


@pytest.fixture
def jwks_url(ec_private_key: Any) -> Iterator[str]:
    jwk = json.loads(ECAlgorithm.to_jwk(ec_private_key.public_key()))
    jwk.update({"kid": "test-key", "use": "sig", "alg": "ES256"})
    body = json.dumps({"keys": [jwk]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/auth/v1/.well-known/jwks.json"
    finally:
        server.shutdown()
        server.server_close()


def test_signing_keys_are_fetched_from_the_jwks_endpoint(
    jwks_url: str, make_token: Callable[..., str]
) -> None:
    verifier = TokenVerifier(issuer=ISSUER, jwks_url=jwks_url)
    assert verifier.is_configured
    assert str(verifier.verify(make_token()).id) == USER_ID


def test_token_signed_by_a_key_not_in_the_jwks_is_rejected(
    jwks_url: str, make_token: Callable[..., str], other_ec_private_key: Any
) -> None:
    verifier = TokenVerifier(issuer=ISSUER, jwks_url=jwks_url)
    with pytest.raises(InvalidTokenError):
        verifier.verify(make_token(key=other_ec_private_key))


def test_unreachable_jwks_endpoint_is_reported_as_unavailable(
    make_token: Callable[..., str],
) -> None:
    # Port 9 (discard) on localhost: nothing is listening.
    verifier = TokenVerifier(issuer=ISSUER, jwks_url="http://127.0.0.1:9/jwks.json")
    with pytest.raises(VerifierUnavailableError):
        verifier.verify(make_token())
