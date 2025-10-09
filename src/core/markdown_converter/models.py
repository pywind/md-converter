"""Domain models for markdown conversion services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .logging import BatchSummary


@dataclass(slots=True)
class ConversionOptions:
    """Configuration for a single conversion run."""

    size_limit_mb: int | None = None
    timeout_s: int | None = None
    image_policy: Literal["extract", "ignore"] = "extract"
    normalize_headings: bool = True
    output_mode: Literal["md", "zip", "both"] = "md"


@dataclass(slots=True)
class ConversionResult:
    """Result metadata for an individual conversion."""

    run_id: str
    output_path: Path
    assets_dir: Path
    warnings: list[str]
    summary: str
    zip_path: Path | None = None
    reused: bool = False


@dataclass(slots=True)
class BatchConversionResult:
    """Aggregate results for a batch conversion request."""

    runs: list[ConversionResult]
    summary: BatchSummary


__all__ = [
    "ConversionOptions",
    "ConversionResult",
    "BatchConversionResult",
]
