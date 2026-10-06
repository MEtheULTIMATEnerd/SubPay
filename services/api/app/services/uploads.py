"""Checks shared by every file upload.

The file's real type is worked out from its contents, not from what the
browser says it is, so a renamed file cannot slip through.
"""

import io
import re
import zipfile
from dataclasses import dataclass

from fastapi import UploadFile

from app.core import errors
from app.core.errors import ApiError

MAX_FILENAME_LENGTH = 255


@dataclass(frozen=True)
class FileKind:
    mime_type: str
    extension: str


PDF = FileKind("application/pdf", "pdf")
DOCX = FileKind("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx")


def read_upload(upload: UploadFile, *, max_bytes: int, what: str) -> bytes:
    """Read an uploaded file fully, refusing anything empty or over the limit."""
    data = upload.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        megabytes = max_bytes // (1024 * 1024)
        raise ApiError(413, "payload_too_large", f"{what} must be {megabytes} MB or smaller")
    if not data:
        raise errors.validation_error("The file is empty", field="file")
    return data


def clean_filename(filename: str | None, fallback: str) -> str:
    """The name to show users. Never used to build a storage path."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:MAX_FILENAME_LENGTH] or fallback


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def is_pdf(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]


def _zip_contains(data: bytes, member: str) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return member in archive.namelist()
    except zipfile.BadZipFile:
        return False


def is_docx(data: bytes) -> bool:
    return _zip_contains(data, "word/document.xml")


def is_xlsx(data: bytes) -> bool:
    return _zip_contains(data, "xl/workbook.xml")


def is_text(data: bytes) -> bool:
    """Plain, readable text: valid UTF-8 with no control bytes other than whitespace."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return not any(ord(ch) < 32 and ch not in "\t\n\r" for ch in text)


def contract_kind(filename: str, data: bytes) -> FileKind:
    """PDF or DOCX, judged by both the extension and the contents."""
    extension = extension_of(filename)
    if extension == "pdf" and is_pdf(data):
        return PDF
    if extension == "docx" and is_docx(data):
        return DOCX
    raise ApiError(415, "unsupported_media_type", "Only PDF or DOCX contracts are supported")


JPEG = FileKind("image/jpeg", "jpg")
PNG = FileKind("image/png", "png")
WEBP = FileKind("image/webp", "webp")
HEIC = FileKind("image/heic", "heic")
XLSX = FileKind("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx")
TEXT = FileKind("text/plain", "txt")
CSV = FileKind("text/csv", "csv")

# Images a browser can show directly, so they get a preview link.
PREVIEWABLE_MIME_TYPES = frozenset({JPEG.mime_type, PNG.mime_type, WEBP.mime_type})

_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")

EVIDENCE_TYPES_MESSAGE = (
    "That file type is not supported. Upload a photo (JPEG, PNG, WebP or HEIC), "
    "or a PDF, Word, Excel, text or CSV file."
)


def evidence_kind(filename: str, data: bytes) -> FileKind:
    """What an evidence file really is, judged by its contents.

    Photos and documents are recognised from their signature whatever they are
    called. Text has no signature, so it also needs a .txt or .csv extension.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return HEIC
    if is_pdf(data):
        return PDF
    if is_docx(data):
        return DOCX
    if is_xlsx(data):
        return XLSX
    extension = extension_of(filename)
    if extension in ("txt", "csv") and is_text(data):
        return CSV if extension == "csv" else TEXT
    raise ApiError(415, "unsupported_media_type", EVIDENCE_TYPES_MESSAGE)
