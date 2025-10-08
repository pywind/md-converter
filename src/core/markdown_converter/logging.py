from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from io import StringIO

from .utils import atomic_write


@dataclass(slots=True)
class StageTimings:
    read_ms: float
    detect_ms: float
    convert_ms: float
    write_ms: float


@dataclass(slots=True)
class RunLogEntry:
    run_id: str
    source: str
    status: str
    mime_type: str
    warnings: list[str]
    error_code: str | None
    timings: StageTimings
    output_path: str
    assets: list[str]
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["timings"] = asdict(self.timings)
        return payload


class RunLogger:
    def __init__(self, log_file: Path) -> None:
        self._log_file = log_file

    def append(self, entry: RunLogEntry) -> None:
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry.to_dict(), ensure_ascii=False)
        with self._log_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


@dataclass(slots=True)
class BatchSummary:
    timestamp: float = field(default_factory=time.time)
    total: int = 0
    successes: int = 0
    failures: int = 0
    warnings: dict[str, int] = field(default_factory=dict)

    def as_row(self, batch_id: str) -> list[str]:
        warning_json = json.dumps(self.warnings, sort_keys=True)
        return [
            batch_id,
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.timestamp)),
            str(self.total),
            str(self.successes),
            str(self.failures),
            warning_json,
        ]


def write_summary_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    atomic_write(path, buffer.getvalue())
