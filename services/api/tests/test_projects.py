"""Project management endpoints (F02), including organisation isolation."""

from collections.abc import Callable
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import MEMBER_A_ID, NO_PROFILE_ID, USER_B_ID, USER_ID
from tests.fakes import FakeDatabase

PROJECTS = "/api/v1/projects"
Headers = Callable[..., dict[str, str]]

HUME = {
    "name": "Hume St Tower",
    "client_name": "Bellrock Construction",
    "site_address": "118 Hume St, Melbourne VIC",
    "start_date": "2026-03-02",
    "end_date": "2026-12-18",
}


def create(client: TestClient, headers: dict[str, str], **overrides: object) -> dict:
    response = client.post(PROJECTS, json={**HUME, **overrides}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# ---- authentication -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", PROJECTS),
        ("POST", PROJECTS),
        ("GET", f"{PROJECTS}/{uuid4()}"),
        ("PATCH", f"{PROJECTS}/{uuid4()}"),
        ("POST", f"{PROJECTS}/{uuid4()}/archive"),
        ("POST", f"{PROJECTS}/{uuid4()}/restore"),
    ],
)
def test_every_project_endpoint_requires_authentication(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


# ---- create -------------------------------------------------------------------


def test_create_project(client: TestClient, as_user: Headers, db: FakeDatabase) -> None:
    project = create(client, as_user())
    me = client.get("/api/v1/me", headers=as_user()).json()

    assert project["name"] == "Hume St Tower"
    assert project["client_name"] == "Bellrock Construction"
    assert project["site_address"] == "118 Hume St, Melbourne VIC"
    assert project["start_date"] == "2026-03-02"
    assert project["end_date"] == "2026-12-18"
    assert project["status"] == "active"
    assert project["organisation_id"] == me["organisation"]["id"]
    assert project["created_by"] == USER_ID
    assert set(project) == {
        "id", "organisation_id", "name", "client_name", "site_address", "status",
        "start_date", "end_date", "created_by", "created_at", "updated_at",
    }  # fmt: skip
    assert len(db.projects) == 1


def test_create_with_only_required_fields(client: TestClient, as_user: Headers) -> None:
    response = client.post(
        PROJECTS, json={"name": " Dock Rd ", "client_name": "Northside"}, headers=as_user()
    )
    assert response.status_code == 201
    project = response.json()
    assert project["name"] == "Dock Rd"
    assert project["site_address"] == ""
    assert project["start_date"] is None and project["end_date"] is None


def test_client_cannot_choose_organisation_creator_status_or_id(
    client: TestClient, as_user: Headers
) -> None:
    other_org = client.get("/api/v1/me", headers=as_user(USER_B_ID)).json()["organisation"]["id"]
    chosen_id = str(uuid4())
    project = create(
        client,
        as_user(),
        id=chosen_id,
        organisation_id=other_org,
        created_by=USER_B_ID,
        status="archived",
    )
    assert project["id"] != chosen_id
    assert project["organisation_id"] != other_org
    assert project["created_by"] == USER_ID
    assert project["status"] == "active"
    # and it is not visible to the organisation the client tried to put it in
    assert client.get(PROJECTS, headers=as_user(USER_B_ID)).json() == {"items": []}


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"client_name": "Builder"}, "name"),
        ({"name": "Tower"}, "client_name"),
        ({"name": "   ", "client_name": "Builder"}, "name"),
        ({"name": "x" * 201, "client_name": "Builder"}, "name"),
        ({"name": "Tower", "client_name": "Builder", "start_date": "not-a-date"}, "start_date"),
    ],
)
def test_create_validation(
    client: TestClient, as_user: Headers, db: FakeDatabase, body: dict, field: str
) -> None:
    response = client.post(PROJECTS, json=body, headers=as_user())
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert field in {d["field"] for d in error["details"]}
    assert db.projects == {}


def test_create_rejects_end_date_before_start_date(client: TestClient, as_user: Headers) -> None:
    response = client.post(
        PROJECTS,
        json={**HUME, "start_date": "2026-06-01", "end_date": "2026-05-01"},
        headers=as_user(),
    )
    assert response.status_code == 422
    assert "End date must not be before start date" in response.text


def test_user_without_a_profile_cannot_create_projects(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    response = client.post(PROJECTS, json=HUME, headers=as_user(NO_PROFILE_ID))
    assert response.status_code == 403
    assert db.projects == {}


# ---- list ---------------------------------------------------------------------


def test_list_is_empty_for_a_new_organisation(client: TestClient, as_user: Headers) -> None:
    response = client.get(PROJECTS, headers=as_user())
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_list_returns_only_the_callers_organisation(client: TestClient, as_user: Headers) -> None:
    a1 = create(client, as_user(), name="A One")
    a2 = create(client, as_user(MEMBER_A_ID), name="A Two")
    b1 = create(client, as_user(USER_B_ID), name="B One")

    a_ids = {p["id"] for p in client.get(PROJECTS, headers=as_user()).json()["items"]}
    member_ids = {
        p["id"] for p in client.get(PROJECTS, headers=as_user(MEMBER_A_ID)).json()["items"]
    }
    b_ids = {p["id"] for p in client.get(PROJECTS, headers=as_user(USER_B_ID)).json()["items"]}

    assert a_ids == {a1["id"], a2["id"]}
    assert member_ids == a_ids
    assert b_ids == {b1["id"]}


def test_list_can_filter_by_status(client: TestClient, as_user: Headers) -> None:
    active = create(client, as_user(), name="Active")
    archived = create(client, as_user(), name="Archived")
    client.post(f"{PROJECTS}/{archived['id']}/archive", headers=as_user())

    def ids(status: str) -> set[str]:
        response = client.get(PROJECTS, params={"status": status}, headers=as_user())
        return {p["id"] for p in response.json()["items"]}

    assert ids("active") == {active["id"]}
    assert ids("archived") == {archived["id"]}


def test_list_supports_limit_and_offset(client: TestClient, as_user: Headers) -> None:
    for n in range(3):
        create(client, as_user(), name=f"Project {n}")
    page = client.get(PROJECTS, params={"limit": 2}, headers=as_user()).json()["items"]
    rest = client.get(PROJECTS, params={"limit": 2, "offset": 2}, headers=as_user()).json()["items"]
    assert len(page) == 2 and len(rest) == 1
    assert {p["id"] for p in page}.isdisjoint({p["id"] for p in rest})


@pytest.mark.parametrize("params", [{"status": "deleted"}, {"limit": 0}, {"limit": 201}])
def test_list_rejects_bad_query_parameters(
    client: TestClient, as_user: Headers, params: dict
) -> None:
    response = client.get(PROJECTS, params=params, headers=as_user())
    assert response.status_code == 422


# ---- retrieve -----------------------------------------------------------------


def test_get_project(client: TestClient, as_user: Headers) -> None:
    project = create(client, as_user())
    response = client.get(f"{PROJECTS}/{project['id']}", headers=as_user())
    assert response.status_code == 200
    assert response.json() == project


def test_colleague_in_the_same_organisation_can_get_the_project(
    client: TestClient, as_user: Headers
) -> None:
    project = create(client, as_user())
    response = client.get(f"{PROJECTS}/{project['id']}", headers=as_user(MEMBER_A_ID))
    assert response.status_code == 200


def test_another_organisations_project_looks_like_it_does_not_exist(
    client: TestClient, as_user: Headers
) -> None:
    project = create(client, as_user())
    other_org = client.get(f"{PROJECTS}/{project['id']}", headers=as_user(USER_B_ID))
    missing = client.get(f"{PROJECTS}/{uuid4()}", headers=as_user(USER_B_ID))

    assert other_org.status_code == missing.status_code == 404
    assert (
        other_org.json()
        == missing.json()
        == {"error": {"code": "not_found", "message": "Project not found"}}
    )


def test_malformed_project_id_is_a_validation_error(client: TestClient, as_user: Headers) -> None:
    response = client.get(f"{PROJECTS}/not-a-uuid", headers=as_user())
    assert response.status_code == 422


# ---- update -------------------------------------------------------------------


def test_update_changes_only_the_fields_sent(client: TestClient, as_user: Headers) -> None:
    project = create(client, as_user())
    response = client.patch(
        f"{PROJECTS}/{project['id']}",
        json={"name": "Hume Street Tower", "end_date": None},
        headers=as_user(),
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Hume Street Tower"
    assert updated["end_date"] is None
    assert updated["client_name"] == project["client_name"]
    assert updated["start_date"] == project["start_date"]
    assert updated["status"] == "active"


def test_member_can_update_the_organisations_project(client: TestClient, as_user: Headers) -> None:
    project = create(client, as_user())
    response = client.patch(
        f"{PROJECTS}/{project['id']}",
        json={"site_address": "120 Hume St"},
        headers=as_user(MEMBER_A_ID),
    )
    assert response.status_code == 200
    assert response.json()["site_address"] == "120 Hume St"


def test_update_cannot_change_status_organisation_or_creator(
    client: TestClient, as_user: Headers
) -> None:
    project = create(client, as_user())
    response = client.patch(
        f"{PROJECTS}/{project['id']}",
        json={
            "name": "Renamed",
            "status": "archived",
            "organisation_id": str(uuid4()),
            "created_by": USER_B_ID,
        },
        headers=as_user(),
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Renamed"
    assert updated["status"] == "active"
    assert updated["organisation_id"] == project["organisation_id"]
    assert updated["created_by"] == USER_ID


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "archived"},  # nothing editable was sent
        {"name": None},
        {"name": "  "},
        {"client_name": None},
        {"start_date": "2026-06-01", "end_date": "2026-05-01"},
    ],
)
def test_update_validation(client: TestClient, as_user: Headers, body: dict) -> None:
    project = create(client, as_user())
    response = client.patch(f"{PROJECTS}/{project['id']}", json=body, headers=as_user())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert client.get(f"{PROJECTS}/{project['id']}", headers=as_user()).json() == project


def test_update_checks_a_single_date_against_the_stored_one(
    client: TestClient, as_user: Headers
) -> None:
    project = create(client, as_user())  # starts 2026-03-02
    response = client.patch(
        f"{PROJECTS}/{project['id']}", json={"end_date": "2026-01-01"}, headers=as_user()
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "end_date", "message": "End date must not be before start date"}
    ]


def test_another_organisation_cannot_update_the_project(
    client: TestClient, as_user: Headers
) -> None:
    project = create(client, as_user())
    response = client.patch(
        f"{PROJECTS}/{project['id']}", json={"name": "Hijacked"}, headers=as_user(USER_B_ID)
    )
    assert response.status_code == 404
    assert client.get(f"{PROJECTS}/{project['id']}", headers=as_user()).json() == project


def test_update_of_a_missing_project_is_404(client: TestClient, as_user: Headers) -> None:
    response = client.patch(f"{PROJECTS}/{uuid4()}", json={"name": "X"}, headers=as_user())
    assert response.status_code == 404


# ---- archive / restore --------------------------------------------------------


def test_archive_and_restore(client: TestClient, as_user: Headers) -> None:
    project = create(client, as_user())
    url = f"{PROJECTS}/{project['id']}"

    archived = client.post(f"{url}/archive", headers=as_user())
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get(url, headers=as_user()).json()["status"] == "archived"

    # archiving twice is harmless
    assert client.post(f"{url}/archive", headers=as_user()).json()["status"] == "archived"

    restored = client.post(f"{url}/restore", headers=as_user())
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"


def test_archived_projects_are_kept_not_deleted(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    project = create(client, as_user())
    client.post(f"{PROJECTS}/{project['id']}/archive", headers=as_user())
    assert len(db.projects) == 1
    assert client.delete(f"{PROJECTS}/{project['id']}", headers=as_user()).status_code == 405


def test_another_organisation_cannot_archive_or_restore_the_project(
    client: TestClient, as_user: Headers
) -> None:
    project = create(client, as_user())
    url = f"{PROJECTS}/{project['id']}"
    assert client.post(f"{url}/archive", headers=as_user(USER_B_ID)).status_code == 404
    assert client.get(url, headers=as_user()).json()["status"] == "active"

    client.post(f"{url}/archive", headers=as_user())
    assert client.post(f"{url}/restore", headers=as_user(USER_B_ID)).status_code == 404
    assert client.get(url, headers=as_user()).json()["status"] == "archived"
