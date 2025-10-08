from __future__ import annotations

from pathlib import Path

from .base import AdapterResponse, BaseMarkitdownAdapter
from ..detection import DocumentType


class XLSXAdapter(BaseMarkitdownAdapter):
    document_type = DocumentType.XLSX

    def convert(self, source: Path, run_assets: Path) -> AdapterResponse:
        response = super().convert(source, run_assets)
        warnings = response.warnings.copy()
        if "|" in response.markdown:
            warnings.append("TABLES_FLATTENED")
        return AdapterResponse(markdown=response.markdown, warnings=warnings, assets=response.assets)
