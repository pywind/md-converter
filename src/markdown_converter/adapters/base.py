from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..detection import DocumentType
from ..utils import slugify


@dataclass(slots=True)
class AdapterResponse:
    markdown: str
    warnings: list[str]
    assets: dict[str, Path]


class Adapter(Protocol):
    def convert(self, source: Path, run_assets: Path) -> AdapterResponse:  # pragma: no cover - interface
        ...


def normalize_markdown(markdown: str) -> str:
    lines = [line.rstrip() for line in markdown.splitlines()]
    return "\n".join(lines) + ("\n" if lines else "")


class BaseMarkitdownAdapter:
    document_type: DocumentType

    def __init__(self) -> None:
        try:
            from markitdown import MarkItDown
        except ModuleNotFoundError as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "markitdown dependency is required for Office/PDF/HTML adapters"
            ) from exc

        self._converter = MarkItDown()

    def _convert_with_metadata(self, source: Path):  # type: ignore[no-untyped-def]
        return self._converter.convert(str(source))

    def convert(self, source: Path, run_assets: Path) -> AdapterResponse:
        result = self._convert_with_metadata(source)
        markdown: str
        warnings: list[str] = []
        assets: dict[str, Path] = {}

        if isinstance(result, str):
            markdown = result
        elif hasattr(result, "text_content"):
            markdown = str(result.text_content)
            attachments = getattr(result, "attachments", None)
            if isinstance(attachments, dict):
                for name, blob in attachments.items():
                    safe_name = slugify(str(name))
                    destination = run_assets / safe_name
                    destination.write_bytes(blob)
                    assets[safe_name] = destination
        else:
            raise RuntimeError("Unsupported markitdown return type")

        markdown = normalize_markdown(markdown)
        return AdapterResponse(markdown=markdown, warnings=warnings, assets=assets)
