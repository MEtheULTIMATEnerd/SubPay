"""Organisation members and invitations (F01)."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_invitation_lookup
from app.api.v1.organisation import OWNER_ONLY_MESSAGE, hash_invite_code
from app.core.config import Settings
from app.core.errors import ApiError
from app.db.supabase import SupabaseRest
from app.repositories.organisation import (
    SupabaseInvitationLookup,
    SupabaseOrganisationRepository,
)
from tests.conftest import MEMBER_A_ID, NO_PROFILE_ID, USER_B_ID, USER_ID
from tests.fakes import FakeDatabase

Headers = Callable[..., dict[str, str]]
API = "/api/v1"
INVITES = f"{API}/organisation/invitations"


def invite(client: TestClient, headers: dict[str, str], email: str = "riley@subpay.test"):
    return client.post(INVITES, json={"email": email}, headers=headers)


def invited(client: TestClient, headers: dict[str, str], email: str = "riley@subpay.test") -> dict:
    response = invite(client, headers, email)
    assert response.status_code == 201, response.text
    return response.json()


# ---- authentication -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{API}/organisation/members"),
        ("GET", INVITES),
        ("POST", INVITES),
        ("DELETE", f"{INVITES}/{uuid4()}"),
    ],
)
def test_member_and_invitation_endpoints_require_authentication(
    client: TestClient, db: FakeDatabase, method: str, path: str
) -> None:
    response = client.request(method, path, json={"email": "riley@subpay.test"})
    assert response.status_code == 401
    assert db.invitations == {}


# ---- members ------------------------------------------------------------------


def test_members_lists_everyone_in_the_callers_organisation_only(
    client: TestClient, as_user: Headers
) -> None:
    for headers in (as_user(), as_user(MEMBER_A_ID)):
        response = client.get(f"{API}/organisation/members", headers=headers)
        assert response.status_code == 200
        members = response.json()["items"]
        assert [(m["full_name"], m["role"]) for m in members] == [
            ("Alex Owner", "owner"),
            ("Morgan Member", "member"),
        ]
        assert set(members[0]) == {"id", "email", "full_name", "role", "created_at"}

    other = client.get(f"{API}/organisation/members", headers=as_user(USER_B_ID)).json()["items"]
    assert [m["full_name"] for m in other] == ["Blake Owner"]


# ---- inviting -----------------------------------------------------------------


def test_an_owner_invites_by_email_and_gets_a_one_time_code(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    response = invite(client, as_user(), "  Riley@SubPay.test ")
    assert response.status_code == 201, response.text
    invitation = response.json()

    assert invitation["email"] == "riley@subpay.test"
    assert invitation["role"] == "member"
    assert invitation["status"] == "pending"
    assert invitation["invited_by"] == USER_ID
    assert invitation["accepted_at"] is None
    expires = datetime.fromisoformat(invitation["expires_at"].replace("Z", "+00:00"))
    assert timedelta(days=6) < expires - datetime.now(timezone.utc) <= timedelta(days=7)

    code = invitation["invite_code"]
    assert len(code) >= 40
    # Only the hash of the code is stored, never the code.
    (stored,) = db.invitations.values()
    assert stored["token_hash"] == hashlib.sha256(code.encode()).hexdigest()
    assert code not in json.dumps(stored, default=str)
    assert "token_hash" not in invitation


def test_every_invitation_gets_a_different_code(client: TestClient, as_user: Headers) -> None:
    first = invited(client, as_user(), "one@subpay.test")["invite_code"]
    second = invited(client, as_user(), "two@subpay.test")["invite_code"]
    assert first != second


def test_the_code_is_never_shown_again(client: TestClient, as_user: Headers) -> None:
    code = invited(client, as_user())["invite_code"]
    response = client.get(INVITES, headers=as_user())
    assert response.status_code == 200
    (listed,) = response.json()["items"]
    assert listed["email"] == "riley@subpay.test"
    assert listed["status"] == "pending"
    assert "invite_code" not in listed and "token_hash" not in listed
    assert code not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": ""},
        {"email": "not-an-address"},
        {"email": "two@at@signs.test"},
        {"email": "spaces in@subpay.test"},
        {"email": "no-dot@subpay"},
        {"email": "x" * 320 + "@subpay.test"},
        {"email": None},
    ],
)
def test_an_invalid_address_is_rejected(
    client: TestClient, as_user: Headers, db: FakeDatabase, body: dict
) -> None:
    response = client.post(INVITES, json=body, headers=as_user())
    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["email"]
    assert db.invitations == {}


def test_the_request_cannot_choose_the_role_organisation_or_expiry(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    org_b = db.organisation_of(UUID(USER_B_ID))
    response = client.post(
        INVITES,
        json={
            "email": "riley@subpay.test",
            "role": "owner",
            "organisation_id": str(org_b),
            "expires_at": "2099-01-01T00:00:00Z",
            "invited_by": USER_B_ID,
        },
        headers=as_user(),
    )
    assert response.status_code == 201
    (stored,) = db.invitations.values()
    assert stored["role"] == "member"
    assert stored["organisation_id"] == db.organisation_of(UUID(USER_ID))
    assert stored["invited_by"] == UUID(USER_ID)
    assert stored["expires_at"] < datetime.now(timezone.utc) + timedelta(days=8)


def test_someone_who_is_already_a_member_cannot_be_invited(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    response = invite(client, as_user(), "MORGAN@subpay.test")
    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "This person is already a member of your organisation"
    )
    assert db.invitations == {}


def test_an_address_can_only_have_one_open_invitation(client: TestClient, as_user: Headers) -> None:
    first = invited(client, as_user())
    response = invite(client, as_user())
    assert response.status_code == 409
    assert "already been invited" in response.json()["error"]["message"]

    # After revoking, the address can be invited again, with a new code.
    assert client.delete(f"{INVITES}/{first['id']}", headers=as_user()).status_code == 204
    assert invited(client, as_user())["invite_code"] != first["invite_code"]


def test_two_organisations_can_invite_the_same_address(
    client: TestClient, as_user: Headers
) -> None:
    invited(client, as_user())
    invited(client, as_user(USER_B_ID))


# ---- owners only --------------------------------------------------------------


def test_a_member_cannot_see_create_or_revoke_invitations(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    invitation = invited(client, as_user())
    member = as_user(MEMBER_A_ID)

    for response in (
        client.get(INVITES, headers=member),
        invite(client, member, "friend@subpay.test"),
        client.delete(f"{INVITES}/{invitation['id']}", headers=member),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["message"] == OWNER_ONLY_MESSAGE
        assert "riley" not in response.text
    assert len(db.invitations) == 1


def test_an_account_without_a_profile_cannot_use_invitations(
    client: TestClient, as_user: Headers
) -> None:
    response = client.get(INVITES, headers=as_user(NO_PROFILE_ID))
    assert response.status_code == 403
    assert "no SubPay profile" in response.json()["error"]["message"]


# ---- organisation isolation -----------------------------------------------------


def test_another_organisations_invitations_are_invisible_and_cannot_be_revoked(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    invitation = invited(client, as_user())
    stranger = as_user(USER_B_ID)

    assert client.get(INVITES, headers=stranger).json()["items"] == []
    response = client.delete(f"{INVITES}/{invitation['id']}", headers=stranger)
    assert response.status_code == 404
    assert response.json() == client.delete(f"{INVITES}/{uuid4()}", headers=stranger).json()
    assert len(db.invitations) == 1


# ---- revoking -----------------------------------------------------------------


def test_an_owner_revokes_an_open_invitation(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    invitation = invited(client, as_user())
    response = client.delete(f"{INVITES}/{invitation['id']}", headers=as_user())
    assert response.status_code == 204 and response.content == b""
    assert db.invitations == {}
    # The link stops working, and revoking twice is a 404.
    assert client.get(f"{API}/invitations/{invitation['invite_code']}").status_code == 404
    assert client.delete(f"{INVITES}/{invitation['id']}", headers=as_user()).status_code == 404


def test_an_accepted_invitation_is_kept_as_a_record(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    invitation = invited(client, as_user())
    db.invitations[UUID(invitation["id"])].update(
        accepted_at=datetime.now(timezone.utc), accepted_by=UUID(MEMBER_A_ID)
    )
    assert client.delete(f"{INVITES}/{invitation['id']}", headers=as_user()).status_code == 404
    (listed,) = client.get(INVITES, headers=as_user()).json()["items"]
    assert listed["status"] == "accepted"


def test_an_expired_invitation_is_listed_as_expired(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    invitation = invited(client, as_user())
    db.invitations[UUID(invitation["id"])]["expires_at"] = datetime.now(timezone.utc) - timedelta(
        minutes=1
    )
    (listed,) = client.get(INVITES, headers=as_user()).json()["items"]
    assert listed["status"] == "expired"


# ---- the public lookup ----------------------------------------------------------


def test_an_invite_link_can_be_looked_up_without_signing_in(
    client: TestClient, as_user: Headers
) -> None:
    code = invited(client, as_user())["invite_code"]
    response = client.get(f"{API}/invitations/{code}")
    assert response.status_code == 200
    preview = response.json()
    assert set(preview) == {"organisation_name", "email", "expires_at"}
    assert preview["organisation_name"] == "Org A Formwork"
    assert preview["email"] == "riley@subpay.test"


def test_wrong_used_and_expired_codes_all_look_the_same(
    client: TestClient, as_user: Headers, db: FakeDatabase
) -> None:
    used = invited(client, as_user(), "used@subpay.test")
    expired = invited(client, as_user(), "expired@subpay.test")
    db.invitations[UUID(used["id"])]["accepted_at"] = datetime.now(timezone.utc)
    db.invitations[UUID(expired["id"])]["expires_at"] = datetime.now(timezone.utc) - timedelta(1)

    answers = [
        client.get(f"{API}/invitations/{code}")
        for code in (used["invite_code"], expired["invite_code"], "x" * 43)
    ]
    assert [a.status_code for a in answers] == [404, 404, 404]
    assert answers[0].json() == answers[1].json() == answers[2].json()


@pytest.mark.parametrize("code", ["short", "has spaces in the middle of it", "x" * 129, "a/b" * 10])
def test_a_malformed_code_never_reaches_the_database(client: TestClient, code: str) -> None:
    assert client.get(f"{API}/invitations/{code}").status_code in (404, 422)


# ---- what we send to Supabase -----------------------------------------------------

BASE = "https://test-project.supabase.co"
USER_TOKEN = "the-callers-own-access-token"
INVITATION_ROW = {
    "id": "11111111-0000-4000-8000-000000000001",
    "email": "riley@subpay.test",
    "role": "member",
    "invited_by": USER_ID,
    "expires_at": "2026-10-11T05:00:00+00:00",
    "accepted_at": None,
    "created_at": "2026-10-04T05:00:00+00:00",
}
Handler = Callable[[httpx2.Request], httpx2.Response]


def recording(handler: Handler, token: str = USER_TOKEN) -> tuple[SupabaseRest, list]:
    requests: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return handler(request)

    http = httpx2.Client(transport=httpx2.MockTransport(record))
    return SupabaseRest(http, base_url=BASE, anon_key="anon-key", access_token=token), requests


def query(request: httpx2.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}


def test_the_token_hash_is_written_but_never_read_back() -> None:
    rest, requests = recording(lambda r: httpx2.Response(201, json=[INVITATION_ROW]))
    repository = SupabaseOrganisationRepository(rest, UUID(USER_ID))

    token_hash = hash_invite_code("the-code")
    repository.create_invitation("riley@subpay.test", token_hash)
    repository.list_invitations()
    repository.delete_open_invitation(UUID(INVITATION_ROW["id"]))

    create, listing, delete = requests
    assert create.method == "POST" and create.url.path == "/rest/v1/organisation_invitations"
    assert json.loads(create.content) == {"email": "riley@subpay.test", "token_hash": token_hash}
    assert create.headers["authorization"] == f"Bearer {USER_TOKEN}"
    for request in (create, listing):
        assert "token_hash" not in query(request)["select"]
    assert delete.method == "DELETE"
    assert query(delete) == {"id": f"eq.{INVITATION_ROW['id']}", "select": "id"}


def test_members_and_role_are_read_as_the_caller() -> None:
    profile = {
        "id": USER_ID,
        "email": "alex@subpay.test",
        "full_name": "Alex Owner",
        "role": "owner",
        "created_at": "2026-09-01T02:00:00+00:00",
    }
    rest, requests = recording(lambda r: httpx2.Response(200, json=[profile]))
    repository = SupabaseOrganisationRepository(rest, UUID(USER_ID))

    assert repository.my_role() == "owner"
    assert [m.full_name for m in repository.list_members()] == ["Alex Owner"]

    role, members = requests
    assert query(role) == {"select": "role", "id": f"eq.{USER_ID}"}
    # No organisation filter: Row Level Security limits the rows.
    assert "organisation_id" not in query(members)
    assert query(members)["select"] == "id,email,full_name,role,created_at"


def test_a_duplicate_invitation_from_the_database_is_a_conflict() -> None:
    body = {"code": "23505", "message": "duplicate key value violates unique constraint"}
    rest, _ = recording(lambda r: httpx2.Response(409, json=body))
    with pytest.raises(ApiError) as caught:
        SupabaseOrganisationRepository(rest, UUID(USER_ID)).create_invitation("a@b.test", "0" * 64)
    assert caught.value.status_code == 409
    assert "already been invited" in caught.value.message


def test_a_refused_insert_stays_forbidden() -> None:
    body = {"code": "42501", "message": "new row violates row-level security policy"}
    rest, _ = recording(lambda r: httpx2.Response(403, json=body))
    with pytest.raises(ApiError) as caught:
        SupabaseOrganisationRepository(rest, UUID(USER_ID)).create_invitation("a@b.test", "0" * 64)
    assert caught.value.status_code == 403


def test_the_public_lookup_calls_the_database_function_as_a_signed_out_caller() -> None:
    row = {
        "organisation_name": "Org A Formwork",
        "email": "riley@subpay.test",
        "expires_at": "2026-10-11T05:00:00+00:00",
    }
    answers = iter([[row], []])
    rest, requests = recording(lambda r: httpx2.Response(200, json=next(answers)), "anon-key")
    lookup = SupabaseInvitationLookup(rest)

    preview = lookup.preview("the-code")
    assert preview is not None and preview.organisation_name == "Org A Formwork"
    assert lookup.preview("wrong-code") is None

    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/rest/v1/rpc/invitation_preview"
    assert json.loads(request.content) == {"p_code": "the-code"}
    assert request.headers["apikey"] == "anon-key"
    assert request.headers["authorization"] == "Bearer anon-key"


def test_the_public_lookup_uses_the_anon_key_never_the_service_role_key() -> None:
    settings = Settings(
        _env_file=None,
        supabase_url=BASE,
        supabase_anon_key="anon-key",
        supabase_service_role_key="service-role-secret",
    )
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=[])

    lookup = get_invitation_lookup(settings, httpx2.Client(transport=httpx2.MockTransport(handler)))
    assert lookup.preview("x" * 43) is None
    assert "service-role-secret" not in str(dict(seen[0].headers))
    assert seen[0].headers["authorization"] == "Bearer anon-key"


def test_the_stored_hash_matches_what_the_database_computes() -> None:
    # encode(sha256(convert_to('code-for-morgan', 'UTF8')), 'hex') in Postgres
    assert hash_invite_code("code-for-morgan") == hashlib.sha256(b"code-for-morgan").hexdigest()
    assert len(hash_invite_code("x")) == 64
