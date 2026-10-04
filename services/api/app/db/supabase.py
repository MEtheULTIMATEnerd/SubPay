"""Talk to the Supabase data API (PostgREST) on behalf of the signed-in user.

Every request carries the caller's own access token, so Postgres Row Level
Security decides what they can read and write. The service-role key is never
used here.

    rest = SupabaseRest(http, base_url=..., anon_key=..., access_token=user.access_token)
    rows = rest.select("projects", {"status": "eq.active"}, order="created_at.desc")
"""

import logging
from typing import Any

import httpx2

from app.core import errors
from app.core.errors import ApiError

logger = logging.getLogger("subpay.api.db")

TIMEOUT_SECONDS = 10.0

# Postgres / PostgREST error codes we translate. Everything else is a 500.
_NOT_NULL_VIOLATION = "23502"
_FOREIGN_KEY_VIOLATION = "23503"
_UNIQUE_VIOLATION = "23505"
_CHECK_VIOLATION = "23514"
_INSUFFICIENT_PRIVILEGE = "42501"


class DatabaseError(ApiError):
    """A database failure, with the Postgres code and message kept for callers
    that want to give a more specific answer."""

    def __init__(self, status_code: int, code: str, message: str, *, pg_code: str, pg_message: str):
        super().__init__(status_code, code, message)
        self.pg_code = pg_code
        self.pg_message = pg_message


def build_http_client() -> httpx2.Client:
    return httpx2.Client(timeout=TIMEOUT_SECONDS)


class SupabaseRest:
    def __init__(
        self,
        http: httpx2.Client,
        *,
        base_url: str,
        anon_key: str,
        access_token: str,
    ) -> None:
        self._http = http
        self._rest_url = f"{base_url.rstrip('/')}/rest/v1" if base_url else ""
        self._anon_key = anon_key
        self._access_token = access_token

    # ---- operations ----------------------------------------------------------

    def select(
        self,
        table: str,
        filters: dict[str, str] | None = None,
        *,
        columns: str = "*",
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": columns, **(filters or {})}
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        if offset:
            params["offset"] = str(offset)
        return self._request("GET", table, params=params)

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        rows = self._request("POST", table, json=row, headers={"Prefer": "return=representation"})
        return rows[0]

    def update(
        self, table: str, filters: dict[str, str], changes: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Returns the rows that were changed. Empty when no row matched or the
        caller is not allowed to see it."""
        if not filters:
            raise ValueError("update() needs at least one filter")
        return self._request(
            "PATCH",
            table,
            params=filters,
            json=changes,
            headers={"Prefer": "return=representation"},
        )

    # ---- plumbing ------------------------------------------------------------

    def _request(self, method: str, table: str, **kwargs: Any) -> list[dict[str, Any]]:
        if not self._rest_url or not self._anon_key:
            logger.error("SUPABASE_URL or SUPABASE_ANON_KEY is not configured")
            raise errors.service_unavailable()

        headers = {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            **kwargs.pop("headers", {}),
        }
        try:
            response = self._http.request(
                method, f"{self._rest_url}/{table}", headers=headers, **kwargs
            )
        except httpx2.HTTPError as exc:
            logger.error("Supabase request failed: %s %s: %s", method, table, exc)
            raise errors.service_unavailable() from exc

        if response.is_success:
            return response.json() if response.content else []
        raise _translate_error(method, table, response)


def _translate_error(method: str, table: str, response: httpx2.Response) -> ApiError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    pg_code = str(body.get("code", "")) if isinstance(body, dict) else ""
    pg_message = str(body.get("message", "")) if isinstance(body, dict) else ""

    def database_error(status_code: int, code: str, message: str) -> DatabaseError:
        return DatabaseError(status_code, code, message, pg_code=pg_code, pg_message=pg_message)

    if response.status_code == 401:
        # Supabase no longer accepts the token (expired or revoked since we checked it).
        return errors.unauthenticated("Your session is invalid or has expired. Sign in again.")
    if pg_code == _CHECK_VIOLATION:
        return database_error(422, "validation_error", "The values sent are not valid")
    if pg_code == _UNIQUE_VIOLATION:
        return database_error(409, "conflict", "That already exists")
    if pg_code == _FOREIGN_KEY_VIOLATION:
        return database_error(409, "conflict", "A related record does not exist")
    if pg_code == _NOT_NULL_VIOLATION:
        return database_error(422, "validation_error", "A required value is missing")
    if pg_code == _INSUFFICIENT_PRIVILEGE or response.status_code == 403:
        return database_error(403, "forbidden", "You do not have permission to do that")
    if response.status_code >= 500:
        logger.error("Supabase %s %s failed: %s %s", method, table, response.status_code, body)
        return errors.service_unavailable()

    logger.error(
        "Unexpected Supabase response: %s %s -> %s %s", method, table, response.status_code, body
    )
    return ApiError(500, "internal_error", "Something went wrong. Please try again.")
