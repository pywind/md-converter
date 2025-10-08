from __future__ import annotations

from pathlib import Path

from .base import AdapterResponse, BaseMarkitdownAdapter
from ..detection import DocumentType


class DOCXAdapter(BaseMarkitdownAdapter):
    document_type = DocumentType.DOCX

    def convert(self, source: Path, run_assets: Path) -> AdapterResponse:
        response = super().convert(source, run_assets)
        return AdapterResponse(markdown=response.markdown, warnings=response.warnings, assets=response.assets)
