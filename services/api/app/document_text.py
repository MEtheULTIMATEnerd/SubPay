"""Bounded document parsing; no mock schedules or external inference."""

import re
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

MAX_TEXT = 1_000_000


def extract(data: bytes, extension: str) -> list[dict]:
    sources = []
    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF signature")
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError("Encrypted PDFs or documents over 100 pages are unsupported")
        for n, page in enumerate(reader.pages, 1):
            sources.append({"reference": f"Page {n}", "text": page.extract_text() or ""})
    else:
        try:
            with ZipFile(BytesIO(data)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024:
                    raise ValueError("DOCX expanded content exceeds limit")
                if "word/document.xml" not in archive.namelist():
                    raise ValueError("Not a DOCX document")
        except BadZipFile as exc:
            raise ValueError("Invalid DOCX container") from exc
        doc = Document(BytesIO(data))
        for n, block in enumerate(doc.iter_inner_content(), 1):
            if isinstance(block, Paragraph):
                sources.append({"reference": f"Block {n}, paragraph", "text": block.text})
            elif isinstance(block, Table):
                for r, row in enumerate(block.rows, 1):
                    sources.append(
                        {
                            "reference": f"Block {n}, table row {r}",
                            "text": " | ".join(c.text for c in row.cells),
                        }
                    )
    if sum(len(s["text"]) for s in sources) > MAX_TEXT:
        raise ValueError("Extracted text exceeds limit")
    return sources


def draft_items(sources: list[dict]) -> list[dict]:
    """Only identifiable numbered lines; uncertain numeric fields remain null."""
    items = []
    for source in sources:
        for line in source["text"].splitlines():
            match = re.match(r"^\s*(\d+(?:\.\d+)*[.)]?)\s+(?:\|\s*)?(.+?)\s*$", line)
            if not match:
                continue
            description = match.group(2).strip()
            if not 3 <= len(description) <= 2000 or not re.search(r"[A-Za-z]", description):
                continue
            items.append(
                {
                    "item_code": match.group(1).rstrip(".)"),
                    "description": description,
                    "source_reference": source["reference"],
                }
            )
            if len(items) > 1000:
                raise ValueError("Too many candidate contract items")
    return items
