"""The real data-access code, against a scripted stand-in for Supabase's HTTP API.

These check WHAT we send to Supabase (whose token, which filters, which
columns) and how its errors are translated. They do not check Row Level
Security itself; supabase/tests/platform_foundation.sql does that.
"""

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx2
import pytest

from app.core.errors import ApiError
from app.db.supabase import DatabaseError, SupabaseRest
from app.repositories.platform import NO_PROFILE_MESSAGE, SupabasePlatformRepository

BASE = "https://test-project.supabase.co"
USER_TOKEN = "the-callers-own-access-token"
USER_ID = UUID("a0000000-0000-4000-8000-000000000001")
ORG_ID = "0b6f3c1e-6d2f-4c0a-9d53-1f0f5a6f7a01"

PROJECT_ROW = {
    "id": "5a0d8a0e-2c9b-4a55-8a8e-0a2b9a6c1d22",
    "organisation_id": ORG_ID,
    "name": "Hume St Tower",
    "client_name": "Bellrock Construction",
    "site_address": "118 Hume St, Melbourne VIC",
    "status": "active",
    "start_date": "2026-03-02",
    "end_date": None,
    "created_by": str(USER_ID),
    "created_at": "2026-09-01T02:05:00.123456+00:00",
    "updated_at": "2026-09-01T02:05:00.123456+00:00",
}
PROFILE_ROW = {
    "id": str(USER_ID),
    "organisation_id": ORG_ID,
    "email": "owner.a@subpay.test",
    "full_name": "Alex Owner",
    "role": "owner",
    "created_at": "2026-09-01T02:00:00+00:00",
    "updated_at": "2026-09-01T02:00:00+00:00",
}
ORG_ROW = {
    "id": ORG_ID,
    "name": "Org A Formwork",
    "created_at": "2026-09-01T02:00:00+00:00",
    "updated_at": "2026-09-01T02:00:00+00:00",
}

Handler = Callable[[httpx2.Request], httpx2.Response]


class Recorder:
    """Records every request and answers with the scripted handler."""

    def __init__(self, handler: Handler) -> None:
        self.requests: list[httpx2.Request] = []
        self._handler = handler

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._handler(request)


def make_rest(handler: Handler, **overrides: Any) -> tuple[SupabaseRest, Recorder]:
    recorder = Recorder(handler)
    http = httpx2.Client(transport=httpx2.MockTransport(recorder))
    options = {"base_url": BASE, "anon_key": "anon-key", "access_token": USER_TOKEN, **overrides}
    return SupabaseRest(http, **options), recorder


def rows(*items: dict, status: int = 200) -> Handler:
    return lambda request: httpx2.Response(status, json=list(items))


def pg_error(status: int, code: str, message: str) -> Handler:
    body = {"code": code, "message": message, "details": None, "hint": None}
    return lambda request: httpx2.Response(status, json=body)


# ---- what we send -------------------------------------------------------------


def test_requests_are_made_as_the_signed_in_user() -> None:
    rest, recorder = make_rest(rows(PROJECT_ROW))
    rest.select("projects")

    request = recorder.requests[0]
    assert request.headers["authorization"] == f"Bearer {USER_TOKEN}"
    assert request.headers["apikey"] == "anon-key"
    assert request.url.path == "/rest/v1/projects"


def test_select_builds_filters_order_and_paging() -> None:
    rest, recorder = make_rest(rows())
    rest.select("projects", {"status": "eq.active"}, order="created_at.desc", limit=20, offset=40)

    params = dict(recorder.requests[0].url.params)
    assert params == {
        "select": "*",
        "status": "eq.active",
        "order": "created_at.desc",
        "limit": "20",
        "offset": "40",
    }


def test_insert_asks_for_the_stored_row_back() -> None:
    rest, recorder = make_rest(rows(PROJECT_ROW, status=201))
    row = rest.insert("projects", {"name": "Hume St Tower", "client_name": "Bellrock"})

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.headers["prefer"] == "return=representation"
    assert json.loads(request.content) == {"name": "Hume St Tower", "client_name": "Bellrock"}
    assert row["id"] == PROJECT_ROW["id"]


def test_update_is_always_filtered() -> None:
    rest, recorder = make_rest(rows(PROJECT_ROW))
    with pytest.raises(ValueError):
        rest.update("projects", {}, {"status": "archived"})
    assert recorder.requests == []

    rest.update("projects", {"id": f"eq.{PROJECT_ROW['id']}"}, {"status": "archived"})
    request = recorder.requests[0]
    assert request.method == "PATCH"
    assert dict(request.url.params) == {"id": f"eq.{PROJECT_ROW['id']}"}


def test_update_that_matches_nothing_returns_no_rows() -> None:
    """A row hidden by Row Level Security looks exactly like a missing row."""
    rest, _ = make_rest(rows())
    assert rest.update("projects", {"id": "eq.x"}, {"name": "Y"}) == []


# ---- how errors come back -----------------------------------------------------


@pytest.mark.parametrize(
    ("handler", "status", "code"),
    [
        (pg_error(401, "PGRST301", "JWT expired"), 401, "unauthenticated"),
        (pg_error(403, "42501", "permission denied for table projects"), 403, "forbidden"),
        (pg_error(409, "23505", "duplicate key value"), 409, "conflict"),
        (pg_error(409, "23503", "violates foreign key constraint"), 409, "conflict"),
        (pg_error(400, "23514", "violates check constraint"), 422, "validation_error"),
        (pg_error(400, "23502", "null value in column"), 422, "validation_error"),
        (pg_error(503, "PGRST000", "could not connect to database"), 503, "service_unavailable"),
        (pg_error(400, "PGRST100", "could not parse filter"), 500, "internal_error"),
        (lambda request: httpx2.Response(502, text="<html>bad gateway</html>"), 503,
         "service_unavailable"),
    ],
)  # fmt: skip
def test_supabase_errors_are_translated(handler: Handler, status: int, code: str) -> None:
    rest, _ = make_rest(handler)
    with pytest.raises(ApiError) as caught:
        rest.select("projects")
    assert (caught.value.status_code, caught.value.code) == (status, code)


def test_database_messages_are_not_shown_to_the_user() -> None:
    rest, _ = make_rest(pg_error(403, "42501", "permission denied for table projects"))
    with pytest.raises(DatabaseError) as caught:
        rest.select("projects")
    assert "projects" not in caught.value.message
    assert caught.value.pg_message == "permission denied for table projects"


def test_network_failure_is_service_unavailable() -> None:
    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    rest, _ = make_rest(unreachable)
    with pytest.raises(ApiError) as caught:
        rest.select("projects")
    assert caught.value.status_code == 503


@pytest.mark.parametrize("missing", [{"base_url": ""}, {"anon_key": ""}])
def test_unconfigured_supabase_is_service_unavailable_without_a_request(missing: dict) -> None:
    rest, recorder = make_rest(rows(), **missing)
    with pytest.raises(ApiError) as caught:
        rest.select("projects")
    assert caught.value.status_code == 503
    assert recorder.requests == []


# ---- repository ---------------------------------------------------------------


def test_get_me_reads_the_callers_profile_then_their_organisation() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        table = request.url.path.rsplit("/", 1)[-1]
        return httpx2.Response(200, json=[PROFILE_ROW if table == "profiles" else ORG_ROW])

    rest, recorder = make_rest(handler)
    me = SupabasePlatformRepository(rest, USER_ID).get_me()

    assert me is not None
    assert me.profile.full_name == "Alex Owner"
    assert me.organisation.name == "Org A Formwork"
    assert recorder.requests[0].url.params["id"] == f"eq.{USER_ID}"
    assert recorder.requests[1].url.params["id"] == f"eq.{ORG_ID}"


def test_get_me_is_none_when_there_is_no_profile() -> None:
    rest, _ = make_rest(rows())
    assert SupabasePlatformRepository(rest, USER_ID).get_me() is None


def test_update_my_name_targets_only_the_caller_and_only_full_name() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        table = request.url.path.rsplit("/", 1)[-1]
        return httpx2.Response(200, json=[PROFILE_ROW if table == "profiles" else ORG_ROW])

    rest, recorder = make_rest(handler)
    SupabasePlatformRepository(rest, USER_ID).update_my_name("Alex O. Owner")

    patch = recorder.requests[0]
    assert patch.method == "PATCH"
    assert dict(patch.url.params) == {"id": f"eq.{USER_ID}"}
    assert json.loads(patch.content) == {"full_name": "Alex O. Owner"}


def test_list_projects_filters_by_status_and_orders_newest_first() -> None:
    rest, recorder = make_rest(rows(PROJECT_ROW))
    projects = SupabasePlatformRepository(rest, USER_ID).list_projects(
        status="active", limit=50, offset=0
    )

    params = dict(recorder.requests[0].url.params)
    assert params["status"] == "eq.active"
    assert params["order"].startswith("created_at.desc")
    assert "organisation_id" not in params  # the database scopes by organisation
    assert projects[0].name == "Hume St Tower"


def test_create_project_sends_only_client_writable_columns() -> None:
    rest, recorder = make_rest(rows(PROJECT_ROW, status=201))
    values = {"name": "Hume St Tower", "client_name": "Bellrock", "site_address": "",
              "start_date": None, "end_date": None}  # fmt: skip
    project = SupabasePlatformRepository(rest, USER_ID).create_project(values)

    sent = json.loads(recorder.requests[0].content)
    assert set(sent) == {"name", "client_name", "site_address", "start_date", "end_date"}
    assert str(project.organisation_id) == ORG_ID  # filled in by the database


def test_get_and_update_return_none_when_the_database_returns_no_row() -> None:
    rest, _ = make_rest(rows())
    repository = SupabasePlatformRepository(rest, USER_ID)
    project_id = UUID(PROJECT_ROW["id"])
    assert repository.get_project(project_id) is None
    assert repository.update_project(project_id, {"name": "X"}) is None


def test_date_constraint_becomes_a_field_error() -> None:
    message = 'new row for relation "projects" violates check constraint "projects_dates_check"'
    rest, _ = make_rest(pg_error(400, "23514", message))
    with pytest.raises(ApiError) as caught:
        SupabasePlatformRepository(rest, USER_ID).update_project(
            UUID(PROJECT_ROW["id"]), {"end_date": "2026-01-01"}
        )
    assert caught.value.status_code == 422
    assert caught.value.details == [
        {"field": "end_date", "message": "End date must not be before start date"}
    ]


def test_creating_a_project_without_a_profile_explains_why() -> None:
    """With no profile there is no organisation, so the database's security rule
    refuses the row. The caller is told why instead of a bare 'forbidden'."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            body = {"code": "42501", "message": "new row violates row-level security policy"}
            return httpx2.Response(403, json=body)
        return httpx2.Response(200, json=[])  # the profile lookup finds nothing

    rest, _ = make_rest(handler)
    with pytest.raises(ApiError) as caught:
        SupabasePlatformRepository(rest, USER_ID).create_project({"name": "X", "client_name": "Y"})
    assert caught.value.status_code == 403
    assert caught.value.message == NO_PROFILE_MESSAGE


def test_a_refused_insert_for_a_user_with_a_profile_stays_a_plain_forbidden() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            body = {"code": "42501", "message": "permission denied for table projects"}
            return httpx2.Response(403, json=body)
        return httpx2.Response(200, json=[{"id": str(USER_ID)}])

    rest, _ = make_rest(handler)
    with pytest.raises(ApiError) as caught:
        SupabasePlatformRepository(rest, USER_ID).create_project({"name": "X", "client_name": "Y"})
    assert caught.value.status_code == 403
    assert caught.value.message != NO_PROFILE_MESSAGE
