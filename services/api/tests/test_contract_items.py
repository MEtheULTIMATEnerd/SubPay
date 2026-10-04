"""Human review of extracted contract items (F05): edit, confirm, reject, reopen."""

from collections.abc import Callable
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import MEMBER_A_ID, USER_B_ID, USER_ID
from tests.files import PDF_BYTES

Headers = Callable[..., dict[str, str]]
API = "/api/v1"


@pytest.fixture
def items(client: TestClient, as_user: Headers) -> list[dict]:
    """A contract in organisation A, extracted into five draft items."""
    project_id = client.post(
        f"{API}/projects", json={"name": "Hume St Tower", "client_name": "Bellrock"},
        headers=as_user(),
    ).json()["id"]  # fmt: skip
    contract_id = client.post(
        f"{API}/projects/{project_id}/contracts",
        files={"file": ("Subcontract.pdf", PDF_BYTES, "application/pdf")},
        headers=as_user(),
    ).json()["id"]
    return client.get(f"{API}/contracts/{contract_id}/items", headers=as_user()).json()["items"]


def reload(client: TestClient, headers: dict[str, str], item: dict) -> dict:
    listing = client.get(f"{API}/contracts/{item['contract_id']}/items", headers=headers).json()
    return next(i for i in listing["items"] if i["id"] == item["id"])


# ---- authentication -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("PATCH", ""), ("POST", "/confirm"), ("POST", "/reject"), ("POST", "/reopen")],
)
def test_every_item_endpoint_requires_authentication(
    client: TestClient, method: str, suffix: str
) -> None:
    response = client.request(
        method, f"{API}/contract-items/{uuid4()}{suffix}", json={"description": "x"}
    )
    assert response.status_code == 401


# ---- confirm / reject / reopen ------------------------------------------------


def test_confirming_records_who_confirmed(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    item = items[1]
    response = client.post(f"{API}/contract-items/{item['id']}/confirm", headers=as_user())
    assert response.status_code == 200
    confirmed = response.json()
    assert confirmed["review_status"] == "confirmed"
    assert confirmed["reviewed_by"] == USER_ID
    assert confirmed["edited_by_human"] is False  # confirming is not an edit
    assert reload(client, as_user(), item)["review_status"] == "confirmed"
    # the other items are untouched
    assert reload(client, as_user(), items[0])["review_status"] == "draft"


def test_a_colleague_can_review_and_is_recorded(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    response = client.post(
        f"{API}/contract-items/{items[0]['id']}/reject", headers=as_user(MEMBER_A_ID)
    )
    assert response.status_code == 200
    assert response.json()["review_status"] == "rejected"
    assert response.json()["reviewed_by"] == MEMBER_A_ID


def test_reopening_returns_the_item_to_draft_and_clears_the_reviewer(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    item_id = items[0]["id"]
    client.post(f"{API}/contract-items/{item_id}/confirm", headers=as_user())
    response = client.post(f"{API}/contract-items/{item_id}/reopen", headers=as_user())
    assert response.status_code == 200
    assert response.json()["review_status"] == "draft"
    assert response.json()["reviewed_by"] is None


def test_review_actions_are_safe_to_repeat(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    item_id = items[0]["id"]
    first = client.post(f"{API}/contract-items/{item_id}/confirm", headers=as_user()).json()
    second = client.post(f"{API}/contract-items/{item_id}/confirm", headers=as_user()).json()
    assert second["review_status"] == "confirmed" and second["reviewed_by"] == first["reviewed_by"]


# ---- edit ---------------------------------------------------------------------


def test_editing_changes_only_the_fields_sent_and_flags_the_item(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    item = items[1]  # 2.1 Formwork, slab edges: 180 m2 at 75 = 13500
    response = client.patch(
        f"{API}/contract-items/{item['id']}",
        json={"quantity": 200, "amount": 15000},
        headers=as_user(),
    )
    assert response.status_code == 200
    edited = response.json()
    assert (edited["quantity"], edited["amount"]) == (200, 15000)
    assert (edited["rate"], edited["unit"], edited["description"]) == (
        75,
        "m²",
        item["description"],
    )
    assert edited["edited_by_human"] is True
    assert edited["review_status"] == "draft"  # editing does not confirm


def test_the_ais_original_values_survive_an_edit(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    item = items[1]
    client.patch(
        f"{API}/contract-items/{item['id']}",
        json={"quantity": 200, "description": "Formwork to slab edges, level 3"},
        headers=as_user(),
    )
    edited = reload(client, as_user(), item)
    assert edited["description"] == "Formwork to slab edges, level 3"
    assert edited["extracted_values"]["quantity"] == 180
    assert edited["extracted_values"]["description"] == "Formwork, slab edges"
    assert edited["extraction_confidence"] == item["extraction_confidence"]


def test_saving_identical_values_is_not_an_edit(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    item = items[1]
    response = client.patch(
        f"{API}/contract-items/{item['id']}",
        json={"quantity": item["quantity"], "unit": item["unit"]},
        headers=as_user(),
    )
    assert response.status_code == 200
    assert response.json()["edited_by_human"] is False


def test_fields_can_be_cleared_when_the_contract_does_not_have_them(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    response = client.patch(
        f"{API}/contract-items/{items[1]['id']}",
        json={"quantity": None, "unit": "  ", "notice_requirement": "", "due_date": None},
        headers=as_user(),
    )
    assert response.status_code == 200
    cleared = response.json()
    assert cleared["quantity"] is None
    assert cleared["unit"] is None  # blank text means "not in the contract", stored as null
    assert cleared["notice_requirement"] is None


def test_notice_details_can_be_added(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    response = client.patch(
        f"{API}/contract-items/{items[0]['id']}",
        json={
            "notice_requirement": " Notify builder 48 hours before each pour ",
            "due_date": "2026-11-01",
            "conditions": "Payable on completion",
        },
        headers=as_user(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notice_requirement"] == "Notify builder 48 hours before each pour"
    assert body["due_date"] == "2026-11-01"
    assert body["conditions"] == "Payable on completion"


def test_review_bookkeeping_cannot_be_set_through_an_edit(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    item = items[0]
    response = client.patch(
        f"{API}/contract-items/{item['id']}",
        json={
            "description": "Preliminaries",
            "review_status": "confirmed",
            "reviewed_by": USER_B_ID,
            "edited_by_human": False,
            "extraction_confidence": 1,
            "extracted_values": {},
            "contract_id": str(uuid4()),
            "item_code": "9.9",
        },
        headers=as_user(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Preliminaries"
    assert body["review_status"] == "draft" and body["reviewed_by"] is None
    assert body["edited_by_human"] is True
    assert body["extraction_confidence"] == item["extraction_confidence"]
    assert body["extracted_values"] == item["extracted_values"]
    assert body["contract_id"] == item["contract_id"] and body["item_code"] == item["item_code"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, None),
        ({"review_status": "confirmed"}, None),  # nothing editable was sent
        ({"description": None}, None),
        ({"description": "   "}, "description"),
        ({"quantity": -1}, "quantity"),
        ({"rate": -0.5}, "rate"),
        ({"amount": "lots"}, "amount"),
        ({"due_date": "next week"}, "due_date"),
        ({"description": "x" * 2001}, "description"),
    ],
)
def test_edit_validation(
    client: TestClient, as_user: Headers, items: list[dict], body: dict, field: str | None
) -> None:
    item = items[1]
    response = client.patch(f"{API}/contract-items/{item['id']}", json=body, headers=as_user())
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    if field:
        assert field in {d["field"] for d in error["details"]}
    assert reload(client, as_user(), item) == item


# ---- isolation ----------------------------------------------------------------


def test_another_organisation_cannot_edit_or_review_items(
    client: TestClient, as_user: Headers, items: list[dict]
) -> None:
    item = items[1]
    b = as_user(USER_B_ID)
    responses = [
        client.patch(f"{API}/contract-items/{item['id']}", json={"amount": 1}, headers=b),
        client.post(f"{API}/contract-items/{item['id']}/confirm", headers=b),
        client.post(f"{API}/contract-items/{item['id']}/reject", headers=b),
        client.post(f"{API}/contract-items/{item['id']}/reopen", headers=b),
    ]
    for response in responses:
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "not_found",
            "message": "Contract item not found",
        }
    assert reload(client, as_user(), item) == item


def test_missing_and_malformed_item_ids(client: TestClient, as_user: Headers) -> None:
    missing = client.post(f"{API}/contract-items/{uuid4()}/confirm", headers=as_user())
    assert missing.status_code == 404
    malformed = client.post(f"{API}/contract-items/not-a-uuid/confirm", headers=as_user())
    assert malformed.status_code == 422
