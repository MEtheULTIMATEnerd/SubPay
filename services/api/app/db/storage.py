"""Supabase Storage on behalf of the signed-in user.

Every request carries the caller's own access token, so the storage policies
(supabase/migrations/..._storage_buckets.sql) decide what they may upload and
read. Buckets are private: files are only ever handed out as short-lived
signed URLs. The service-role key is never used here.
"""

import logging
from typing import Protocol
from urllib.parse import quote

import httpx2

from app.core import errors
from app.core.errors import ApiError

logger = logging.getLogger("subpay.api.storage")

UPLOAD_TIMEOUT_SECONDS = 120.0


class FileStorage(Protocol):
    """What the application needs from file storage (lets tests use a fake)."""

    def upload(self, bucket: str, path: str, content: bytes, content_type: str) -> None: ...

    def signed_url(
        self, bucket: str, path: str, *, expires_in: int, download_as: str | None = None
    ) -> str | None: ...

    def signed_urls(self, bucket: str, paths: list[str], *, expires_in: int) -> dict[str, str]: ...


class SupabaseStorage:
    def __init__(
        self,
        http: httpx2.Client,
        *,
        base_url: str,
        anon_key: str,
        access_token: str,
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._storage_url = f"{self._base_url}/storage/v1" if base_url else ""
        self._anon_key = anon_key
        self._access_token = access_token

    def upload(self, bucket: str, path: str, content: bytes, content_type: str) -> None:
        """Store a new file. Never overwrites: an existing object is a conflict."""
        response = self._request(
            "POST",
            f"object/{bucket}/{_quote_path(path)}",
            content=content,
            headers={"Content-Type": content_type, "x-upsert": "false"},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
        if not response.is_success:
            raise _translate_error("upload", bucket, response)

    def signed_url(
        self, bucket: str, path: str, *, expires_in: int, download_as: str | None = None
    ) -> str | None:
        """A temporary link to a private file, or None when the caller may not read it
        (or it does not exist: storage reports both the same way)."""
        response = self._request(
            "POST",
            f"object/sign/{bucket}/{_quote_path(path)}",
            json={"expiresIn": expires_in},
        )
        if _status(response) in (400, 404):
            return None
        if not response.is_success:
            raise _translate_error("sign", bucket, response)

        signed = response.json().get("signedURL") or response.json().get("signedUrl")
        if not signed:
            logger.error("Supabase Storage returned no signed URL for %s", bucket)
            raise errors.service_unavailable()
        url = f"{self._storage_url}/{signed.lstrip('/')}"
        if download_as:
            url += f"{'&' if '?' in url else '?'}download={quote(download_as)}"
        return url

    def signed_urls(self, bucket: str, paths: list[str], *, expires_in: int) -> dict[str, str]:
        """Temporary links for several files in one request, keyed by path.
        Files the caller may not read are simply left out."""
        if not paths:
            return {}
        response = self._request(
            "POST", f"object/sign/{bucket}", json={"expiresIn": expires_in, "paths": paths}
        )
        if not response.is_success:
            raise _translate_error("sign", bucket, response)
        links: dict[str, str] = {}
        for entry in response.json():
            signed = entry.get("signedURL") or entry.get("signedUrl")
            if signed and not entry.get("error"):
                links[entry["path"]] = f"{self._storage_url}/{signed.lstrip('/')}"
        return links

    def _request(self, method: str, path: str, **kwargs) -> httpx2.Response:
        if not self._storage_url or not self._anon_key:
            logger.error("SUPABASE_URL or SUPABASE_ANON_KEY is not configured")
            raise errors.service_unavailable()
        headers = {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {self._access_token}",
            **kwargs.pop("headers", {}),
        }
        try:
            return self._http.request(
                method, f"{self._storage_url}/{path}", headers=headers, **kwargs
            )
        except httpx2.HTTPError as exc:
            logger.error("Supabase Storage request failed: %s %s: %s", method, path, exc)
            raise errors.service_unavailable() from exc


def _quote_path(path: str) -> str:
    return "/".join(quote(part, safe="") for part in path.split("/"))


def _body(response: httpx2.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _status(response: httpx2.Response) -> int:
    """Storage sometimes answers HTTP 400 with the real status inside the body."""
    inner = str(_body(response).get("statusCode", ""))
    return int(inner) if inner.isdigit() else response.status_code


def _translate_error(action: str, bucket: str, response: httpx2.Response) -> ApiError:
    status = _status(response)
    message = str(_body(response).get("message", "")).lower()

    if status == 401:
        return errors.unauthenticated("Your session is invalid or has expired. Sign in again.")
    if status == 403 or "row-level security" in message:
        return errors.forbidden()
    if status == 409 or "already exists" in message or "duplicate" in message:
        return errors.conflict("That file has already been uploaded")
    if status == 413 or "maximum allowed size" in message or "too large" in message:
        return ApiError(413, "payload_too_large", "The file is too large")
    if status == 415 or "mime type" in message:
        return ApiError(415, "unsupported_media_type", "That file type is not supported")
    if status >= 500:
        logger.error("Supabase Storage %s on %s failed: %s", action, bucket, response.status_code)
        return errors.service_unavailable()

    logger.error(
        "Unexpected Supabase Storage response for %s on %s: %s %s",
        action,
        bucket,
        response.status_code,
        _body(response),
    )
    return ApiError(500, "internal_error", "Something went wrong. Please try again.")
