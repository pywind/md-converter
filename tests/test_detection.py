import pytest

from core.markdown_converter.detection import (
    DetectionError,
    DocumentType,
    detect_document_type,
)


def test_detect_document_type_html(tmp_path):
    sample = tmp_path / "sample.html"
    sample.write_text("<html><body>Hi</body></html>")
    result = detect_document_type(sample)
    assert result.document_type == DocumentType.HTML
    assert result.mime_type == "text/html"


def test_detect_document_type_unknown_extension(tmp_path):
    sample = tmp_path / "sample.xyz"
    sample.write_text("dummy")
    with pytest.raises(DetectionError) as exc:
        detect_document_type(sample)
    assert "Unsupported file extension" in str(exc.value)
