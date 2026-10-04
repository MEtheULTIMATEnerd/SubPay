"""File checks shared by all uploads, and the request size limit."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.limits import BodySizeLimitMiddleware
from app.services import uploads
from tests.files import PDF_BYTES, docx_bytes, zip_bytes


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Subcontract.pdf", "Subcontract.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\kin\\Desktop\\contract.docx", "contract.docx"),
        ("  spaced name.pdf  ", "spaced name.pdf"),
        ("bad\x00name\x1f.pdf", "badname.pdf"),
        ("", "contract"),
        (None, "contract"),
        ("/", "contract"),
        ("a" * 300 + ".pdf", "a" * 255),
    ],
)
def test_clean_filename(given: str | None, expected: str) -> None:
    assert uploads.clean_filename(given, fallback="contract") == expected


def test_pdf_and_docx_are_recognised_by_their_contents() -> None:
    assert uploads.is_pdf(PDF_BYTES)
    assert uploads.is_pdf(b"\n\n" + PDF_BYTES)  # some scanners put whitespace first
    assert not uploads.is_pdf(b"PK\x03\x04 not a pdf")
    assert uploads.is_docx(docx_bytes())
    assert not uploads.is_docx(zip_bytes())  # a zip, but not a Word document
    assert not uploads.is_docx(b"PK\x03\x04 truncated")
    assert not uploads.is_docx(PDF_BYTES)


def _echo_app(max_bytes: int) -> FastAPI:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)

    @app.post("/echo")
    async def echo(payload: dict) -> dict:
        return {"keys": len(payload)}

    return app


def test_requests_within_the_limit_pass_through() -> None:
    client = TestClient(_echo_app(max_bytes=1000))
    assert client.post("/echo", json={"a": 1}).json() == {"keys": 1}


def test_an_oversized_request_is_refused_from_its_declared_length() -> None:
    client = TestClient(_echo_app(max_bytes=100))
    response = client.post("/echo", json={"a": "x" * 500})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_an_oversized_request_without_a_declared_length_is_refused_while_reading() -> None:
    client = TestClient(_echo_app(max_bytes=100))

    def chunks():
        yield b'{"a": "'
        yield b"x" * 500
        yield b'"}'

    response = client.post("/echo", content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_the_api_applies_the_limit(client: TestClient) -> None:
    """The real app refuses a body far beyond the largest allowed upload, before reading it."""
    response = client.post(
        "/api/v1/health",
        content=b"",
        headers={"Content-Length": str(500 * 1024 * 1024)},
    )
    assert response.status_code == 413
