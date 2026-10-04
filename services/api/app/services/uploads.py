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


def is_docx(data: bytes) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def contract_kind(filename: str, data: bytes) -> FileKind:
    """PDF or DOCX, judged by both the extension and the contents."""
    extension = extension_of(filename)
    if extension == "pdf" and is_pdf(data):
        return PDF
    if extension == "docx" and is_docx(data):
        return DOCX
    raise ApiError(415, "unsupported_media_type", "Only PDF or DOCX contracts are supported")
