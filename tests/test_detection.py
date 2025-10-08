from pathlib import Path

import pytest

from markdown_converter.detection import DetectionError, detect_document_type, DocumentType


def test_detect_txt(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello", encoding="utf-8")
    result = detect_document_type(file_path)
    assert result.document_type == DocumentType.TXT
    assert result.mime_type == "text/plain"


def test_detect_pdf_mismatch(tmp_path: Path) -> None:
    file_path = tmp_path / "fake.pdf"
    file_path.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(DetectionError):
        detect_document_type(file_path)
