from __future__ import annotations

from pathlib import Path

from .base import AdapterResponse
from ..detection import DocumentType
from ..utils import normalize_newlines


class TXTAdapter:
    document_type = DocumentType.TXT

    def convert(self, source: Path, run_assets: Path) -> AdapterResponse:  # type: ignore[override]
        text = source.read_text(encoding="utf-8", errors="ignore")
        markdown = normalize_newlines(text)
        return AdapterResponse(markdown=markdown, warnings=[], assets={})
