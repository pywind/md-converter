from __future__ import annotations

from pathlib import Path

from .base import AdapterResponse, BaseMarkitdownAdapter
from ..detection import DocumentType


class PPTXAdapter(BaseMarkitdownAdapter):
    document_type = DocumentType.PPTX

    def convert(self, source: Path, run_assets: Path) -> AdapterResponse:
        response = super().convert(source, run_assets)
        markdown_lines = []
        for line in response.markdown.splitlines():
            if line.startswith("# "):
                markdown_lines.append("## " + line[2:])
            else:
                markdown_lines.append(line)
        normalized = "\n".join(markdown_lines) + "\n"
        return AdapterResponse(markdown=normalized, warnings=response.warnings, assets=response.assets)
