"""What we send to Supabase Storage, and how its answers are translated."""

from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.core.errors import ApiError
from app.db.storage import SupabaseStorage

BASE = "https://test-project.supabase.co"
USER_TOKEN = "the-callers-own-access-token"
PATH = "aaaaaaaa-0000-4000-8000-000000000001/cccccccc-0000-4000-8000-000000000001/original.pdf"

Handler = Callable[[httpx2.Request], httpx2.Response]


def make_storage(
    handler: Handler, **overrides: Any
) -> tuple[SupabaseStorage, list[httpx2.Request]]:
    requests: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return handler(request)

    http = httpx2.Client(transport=httpx2.MockTransport(record))
    options = {"base_url": BASE, "anon_key": "anon-key", "access_token": USER_TOKEN, **overrides}
    return SupabaseStorage(http, **options), requests


def storage_error(http_status: int, status_code: str, message: str) -> Handler:
    body = {"statusCode": status_code, "error": "Error", "message": message}
    return lambda request: httpx2.Response(http_status, json=body)


def test_upload_sends_the_file_as_the_signed_in_user_without_overwriting() -> None:
    storage, requests = make_storage(
        lambda r: httpx2.Response(200, json={"Key": f"contracts/{PATH}"})
    )
    storage.upload("contracts", PATH, b"%PDF-1.7 ...", "application/pdf")

    (request,) = requests
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}/storage/v1/object/contracts/{PATH}"
    assert request.headers["authorization"] == f"Bearer {USER_TOKEN}"
    assert request.headers["apikey"] == "anon-key"
    assert request.headers["content-type"] == "application/pdf"
    assert request.headers["x-upsert"] == "false"
    assert request.content == b"%PDF-1.7 ..."


def test_signed_url_is_a_full_link_with_the_download_name() -> None:
    signed = f"/object/sign/contracts/{PATH}?token=abc123"
    storage, requests = make_storage(lambda r: httpx2.Response(200, json={"signedURL": signed}))
    url = storage.signed_url("contracts", PATH, expires_in=300, download_as="Sub contract.pdf")

    (request,) = requests
    assert str(request.url) == f"{BASE}/storage/v1/object/sign/contracts/{PATH}"
    assert request.headers["authorization"] == f"Bearer {USER_TOKEN}"
    assert request.content == b'{"expiresIn":300}'
    assert url == f"{BASE}/storage/v1{signed}&download=Sub%20contract.pdf"


@pytest.mark.parametrize(
    "handler",
    [
        storage_error(400, "404", "Object not found"),
        storage_error(404, "404", "Object not found"),
        lambda r: httpx2.Response(404, text="not found"),
    ],
)
def test_a_file_the_caller_cannot_read_has_no_signed_url(handler: Handler) -> None:
    """Storage reports 'hidden by policy' and 'does not exist' identically."""
    storage, _ = make_storage(handler)
    assert storage.signed_url("contracts", PATH, expires_in=300) is None


@pytest.mark.parametrize(
    ("handler", "status", "code"),
    [
        (storage_error(400, "403", "new row violates row-level security policy"), 403, "forbidden"),
        (storage_error(403, "403", "Unauthorized"), 403, "forbidden"),
        (storage_error(401, "401", "jwt expired"), 401, "unauthenticated"),
        (storage_error(400, "409", "The resource already exists"), 409, "conflict"),
        (storage_error(413, "413", "The object exceeded the maximum allowed size"), 413,
         "payload_too_large"),
        (storage_error(415, "415", "mime type text/html is not supported"), 415,
         "unsupported_media_type"),
        (storage_error(500, "500", "Internal error"), 503, "service_unavailable"),
        (lambda r: httpx2.Response(502, text="<html>bad gateway</html>"), 503,
         "service_unavailable"),
    ],
)  # fmt: skip
def test_upload_errors_are_translated(handler: Handler, status: int, code: str) -> None:
    storage, _ = make_storage(handler)
    with pytest.raises(ApiError) as caught:
        storage.upload("contracts", PATH, b"x", "application/pdf")
    assert (caught.value.status_code, caught.value.code) == (status, code)


def test_network_failure_is_service_unavailable() -> None:
    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    storage, _ = make_storage(unreachable)
    with pytest.raises(ApiError) as caught:
        storage.upload("contracts", PATH, b"x", "application/pdf")
    assert caught.value.status_code == 503


@pytest.mark.parametrize("missing", [{"base_url": ""}, {"anon_key": ""}])
def test_unconfigured_storage_is_service_unavailable_without_a_request(missing: dict) -> None:
    storage, requests = make_storage(lambda r: httpx2.Response(200), **missing)
    with pytest.raises(ApiError) as caught:
        storage.upload("contracts", PATH, b"x", "application/pdf")
    assert caught.value.status_code == 503
    assert requests == []
