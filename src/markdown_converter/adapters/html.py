from __future__ import annotations

from pathlib import Path

from .base import AdapterResponse, BaseMarkitdownAdapter
from ..detection import DocumentType


class HTMLAdapter(BaseMarkitdownAdapter):
    document_type = DocumentType.HTML

    def convert(self, source: Path, run_assets: Path) -> AdapterResponse:
        response = super().convert(source, run_assets)
        return response
