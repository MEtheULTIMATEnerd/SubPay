"""GET / PATCH /api/v1/me (F01: user profile and organisation membership)."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import MEMBER_A_ID, NO_PROFILE_ID, USER_B_ID, USER_ID

ME = "/api/v1/me"
Headers = Callable[..., dict[str, str]]


def test_me_requires_authentication(client: TestClient) -> None:
    assert client.get(ME).status_code == 401
    assert client.patch(ME, json={"full_name": "X"}).status_code == 401


def test_me_returns_profile_and_organisation(client: TestClient, as_user: Headers) -> None:
    response = client.get(ME, headers=as_user())
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["id"] == USER_ID
    assert body["profile"]["full_name"] == "Alex Owner"
    assert body["profile"]["role"] == "owner"
    assert body["organisation"]["name"] == "Org A Formwork"
    assert body["profile"]["organisation_id"] == body["organisation"]["id"]
    assert set(body["profile"]) == {
        "id", "organisation_id", "email", "full_name", "role", "created_at", "updated_at",
    }  # fmt: skip


def test_each_user_gets_their_own_organisation(client: TestClient, as_user: Headers) -> None:
    a = client.get(ME, headers=as_user(USER_ID)).json()
    member = client.get(ME, headers=as_user(MEMBER_A_ID)).json()
    b = client.get(ME, headers=as_user(USER_B_ID)).json()
    assert member["organisation"]["id"] == a["organisation"]["id"]
    assert member["profile"]["role"] == "member"
    assert b["organisation"]["id"] != a["organisation"]["id"]
    assert b["organisation"]["name"] == "Org B Scaffolding"


def test_update_own_name(client: TestClient, as_user: Headers) -> None:
    response = client.patch(ME, json={"full_name": "  Alex O. Owner  "}, headers=as_user())
    assert response.status_code == 200
    assert response.json()["profile"]["full_name"] == "Alex O. Owner"
    assert client.get(ME, headers=as_user()).json()["profile"]["full_name"] == "Alex O. Owner"
    # nobody else was changed
    assert client.get(ME, headers=as_user(MEMBER_A_ID)).json()["profile"]["full_name"] == (
        "Morgan Member"
    )


def test_role_and_organisation_cannot_be_changed_through_me(
    client: TestClient, as_user: Headers
) -> None:
    before = client.get(ME, headers=as_user(MEMBER_A_ID)).json()
    response = client.patch(
        ME,
        json={
            "full_name": "Morgan Member",
            "role": "owner",
            "organisation_id": "00000000-0000-4000-8000-000000000000",
        },
        headers=as_user(MEMBER_A_ID),
    )
    assert response.status_code == 200
    after = response.json()
    assert after["profile"]["role"] == "member"
    assert after["profile"]["organisation_id"] == before["profile"]["organisation_id"]


def test_blank_name_is_rejected(client: TestClient, as_user: Headers) -> None:
    response = client.patch(ME, json={"full_name": "   "}, headers=as_user())
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "full_name"


def test_signed_in_user_without_a_profile_gets_a_clear_403(
    client: TestClient, as_user: Headers
) -> None:
    response = client.get(ME, headers=as_user(NO_PROFILE_ID))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
