from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import local_contracts
from tests.test_integrated import HEADERS, client_for

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def pdf(text=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    if text:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 30 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def docx():
    document = Document()
    document.add_paragraph("Construction subcontract: actual terms")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "2.1"
    table.cell(0, 1).text = "Install electrical conduit"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


@pytest.fixture
def workflow(tmp_path):
    c = client_for(tmp_path)
    project = c.post("/projects", json={"name": "Site"}, headers=HEADERS).json()["id"]
    return c, f"/projects/{project}/contracts", tmp_path


def upload(c, base, data, filename="schedule.pdf", mime="application/pdf", headers=HEADERS):
    return c.post(base, files={"file": (filename, data, mime)}, headers=headers)


def test_real_pdf_and_file_retention(workflow):
    c, base, directory = workflow
    data = pdf("1.1 Formwork slab soffit")
    result = upload(c, base, data, "../../unsafe.pdf")
    assert result.status_code == 201
    record = result.json()
    assert "Formwork slab soffit" in record["extracted_text"]
    assert (directory / record["storage_path"]).read_bytes() == data
    assert record["original_filename"] == "unsafe.pdf"
    items = c.get(f"{base}/{record['id']}/items", headers=HEADERS).json()
    assert items[0]["source_reference"] == "Page 1"
    assert items[0]["contract_id"] == record["id"]
    assert items[0]["review_status"] == "draft"
    assert items[0]["amount"] is None
    assert c.get(f"{base}/{record['id']}/original", headers=HEADERS).content == data


def test_docx_paragraphs_and_tables(workflow):
    c, base, _ = workflow
    record = upload(c, base, docx(), "contract.docx", DOCX).json()
    assert "actual terms" in record["extracted_text"]
    items = c.get(f"{base}/{record['id']}/items", headers=HEADERS).json()
    assert items[0]["description"] == "Install electrical conduit"
    assert "table row" in items[0]["source_reference"]


def test_content_not_filename(workflow):
    c, base, _ = workflow
    a = upload(c, base, pdf("1.1 Install formwork")).json()
    b = upload(c, base, pdf("2.2 Install conduit")).json()
    same = upload(c, base, pdf("1.1 Install formwork"), "electrical-fitout.pdf").json()
    assert a["extracted_text"] != b["extracted_text"]
    assert a["extracted_text"] == same["extracted_text"]
    assert a["sources"] == same["sources"]


@pytest.mark.parametrize(
    "filename,mime,data,status",
    [
        ("x.txt", "text/plain", b"hello", 415),
        ("x.pdf", DOCX, pdf(), 415),
        ("x.docx", "application/pdf", docx(), 415),
        ("x.pdf", "application/pdf", b"not pdf", 422),
        ("x.docx", DOCX, b"not zip", 422),
        ("x.pdf", "application/pdf", b"%PDF-1.7\nbroken", 422),
    ],
)
def test_rejected_documents_leave_no_records_or_files(workflow, filename, mime, data, status):
    c, base, directory = workflow
    assert upload(c, base, data, filename, mime).status_code == status
    assert c.get(base, headers=HEADERS).json() == []
    assert not list(directory.rglob("*.pdf"))
    assert not list(directory.rglob("*.docx"))


def test_size_limit(workflow, monkeypatch):
    c, base, _ = workflow
    monkeypatch.setattr(local_contracts, "MAX_UPLOAD", 10)
    assert upload(c, base, pdf("1.1 Formwork")).status_code == 413


def test_empty_pdf_and_manual_review_persist(workflow):
    c, base, directory = workflow
    contract = upload(c, base, pdf()).json()
    assert "OCR" in contract["limitation"]
    path = f"{base}/{contract['id']}/items"
    assert c.get(path, headers=HEADERS).json() == []
    item = c.post(
        path, json={"description": "Manually read contract requirement"}, headers=HEADERS
    ).json()
    assert item["origin"] == "manual"
    assert item["extracted_description"] is None
    assert item["review_status"] == "draft"
    reviewed = c.post(
        f"{path}/{item['id']}/review", json={"status": "confirmed"}, headers=HEADERS
    ).json()
    assert reviewed["reviewed_by"] == "local-development-user"
    assert reviewed["reviewed_at"]
    assert client_for(directory).get(path, headers=HEADERS).json() == [reviewed]


def test_edit_review_and_cross_project(workflow):
    c, base, _ = workflow
    contract = upload(c, base, pdf("1.1 Install formwork")).json()
    path = f"{base}/{contract['id']}/items"
    item = c.get(path, headers=HEADERS).json()[0]
    url = f"{path}/{item['id']}"
    edited = c.patch(
        url, json={"description": "Corrected formwork", "quantity": 20}, headers=HEADERS
    ).json()
    assert edited["extracted_description"] == "Install formwork"
    assert edited["source_reference"] == "Page 1"
    for status in ["confirmed", "draft", "rejected"]:
        result = c.post(url + "/review", json={"status": status}, headers=HEADERS).json()
        assert result["review_status"] == status
        assert (result["reviewed_at"] is None) == (status == "draft")
    assert (
        c.patch(url, json={"description": "No silent changes"}, headers=HEADERS).status_code == 409
    )
    other = c.post("/projects", json={"name": "Other"}, headers=HEADERS).json()["id"]
    assert (
        c.get(f"/projects/{other}/contracts/{contract['id']}", headers=HEADERS).status_code == 404
    )
    assert (
        c.post(
            f"/projects/{other}/contracts/{contract['id']}/items",
            json={"description": "Wrong project"},
            headers=HEADERS,
        ).status_code
        == 404
    )
    assert upload(c, f"/projects/{uuid4()}/contracts", pdf()).status_code == 404


def test_access_boundary(workflow):
    c, base, _ = workflow
    for headers in [{}, {"Authorization": "Bearer invalid"}]:
        assert upload(c, base, pdf(), headers=headers).status_code == 401
        assert c.get(base, headers=headers).status_code == 401


def test_database_failure_cleans_original(workflow, monkeypatch):
    c, base, directory = workflow

    def fail(*args, **kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(local_contracts, "add_item", fail)
    with pytest.raises(RuntimeError):
        upload(c, base, pdf("1.1 Install formwork"))
    assert not list(directory.rglob("*.pdf"))
    assert c.get(base, headers=HEADERS).json() == []


def test_unstructured_text_preserved_for_manual_entry(workflow):
    c, base, _ = workflow
    record = upload(c, base, pdf("Supply concrete to the site as directed")).json()
    assert "Supply concrete" in record["extracted_text"]
    assert "manually" in record["limitation"]
    assert record["draft_item_count"] == 0


def test_original_write_failure_creates_no_contract(workflow, monkeypatch):
    c, base, directory = workflow
    from pathlib import Path

    original_open = Path.open

    def fail_write(self, mode="r", *args, **kwargs):
        if mode == "xb":
            raise OSError("simulated disk failure")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_write)
    with pytest.raises(OSError):
        upload(c, base, pdf("1.1 Install formwork"))
    assert c.get(base, headers=HEADERS).json() == []
    assert not list(directory.rglob("*.pdf"))
