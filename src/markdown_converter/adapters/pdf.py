from __future__ import annotations

from pathlib import Path

from .base import AdapterResponse, BaseMarkitdownAdapter
from ..detection import DocumentType


class PDFAdapter(BaseMarkitdownAdapter):
    document_type = DocumentType.PDF

    def convert(self, source: Path, run_assets: Path) -> AdapterResponse:
        response = super().convert(source, run_assets)
        warnings = response.warnings.copy()
        if len(response.markdown.strip()) < 40:
            warnings.append("IMAGE_HEAVY_PDF")
        return AdapterResponse(markdown=response.markdown, warnings=warnings, assets=response.assets)
