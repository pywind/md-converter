from __future__ import annotations

import mimetypes
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DocumentType(str, Enum):
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    PDF = "pdf"
    HTML = "html"
    TXT = "txt"
    EML = "eml"

    @property
    def extension(self) -> str:
        return f".{self.value}"


@dataclass(slots=True)
class DetectionResult:
    document_type: DocumentType
    mime_type: str
    extension: str


EXTENSION_MAP: dict[str, DocumentType] = {
    ".docx": DocumentType.DOCX,
    ".pptx": DocumentType.PPTX,
    ".xlsx": DocumentType.XLSX,
    ".pdf": DocumentType.PDF,
    ".html": DocumentType.HTML,
    ".htm": DocumentType.HTML,
    ".txt": DocumentType.TXT,
    ".eml": DocumentType.EML,
}

MIME_MAP: dict[DocumentType, str] = {
    DocumentType.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DocumentType.PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    DocumentType.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    DocumentType.PDF: "application/pdf",
    DocumentType.HTML: "text/html",
    DocumentType.TXT: "text/plain",
    DocumentType.EML: "message/rfc822",
}


class DetectionError(RuntimeError):
    """Raised when format detection fails."""


def sniff_mime(path: Path) -> str:
    extension = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))
    if extension in {".docx", ".pptx", ".xlsx"}:
        if zipfile.is_zipfile(path):
            return MIME_MAP[EXTENSION_MAP[extension]]
        return "application/octet-stream"
    if extension == ".pdf":
        with path.open("rb") as handle:
            header = handle.read(5)
        if header.startswith(b"%PDF"):
            return MIME_MAP[DocumentType.PDF]
        return "application/octet-stream"
    if extension in {".html", ".htm"}:
        with path.open("rb") as handle:
            sample = handle.read(512).lower()
        if b"<html" in sample or b"<!doctype html" in sample:
            return MIME_MAP[DocumentType.HTML]
        return "application/octet-stream"
    if extension == ".eml":
        return MIME_MAP[DocumentType.EML]
    if extension == ".txt":
        return MIME_MAP[DocumentType.TXT]
    return mime or "application/octet-stream"


def detect_document_type(path: Path) -> DetectionResult:
    extension = path.suffix.lower()
    ext_type = EXTENSION_MAP.get(extension)
    if not ext_type:
        raise DetectionError(f"Unsupported file extension: {extension or '<none>'}")
    mime = sniff_mime(path)
    expected_mime = MIME_MAP[ext_type]
    if mime != expected_mime:
        raise DetectionError(
            f"MIME sniff mismatch: expected {expected_mime}, detected {mime or 'unknown'}",
        )
    return DetectionResult(document_type=ext_type, mime_type=mime, extension=extension)
