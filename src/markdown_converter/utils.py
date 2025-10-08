from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .config import AppConfig


SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(slots=True)
class RunPaths:
    run_id: str
    base_dir: Path
    output_file: Path
    assets_dir: Path
    log_file: Path


def slugify(value: str, max_length: int = 120) -> str:
    normalized = SAFE_FILENAME_RE.sub("-", value.strip())
    normalized = re.sub("-+", "-", normalized)
    normalized = normalized.replace("-.", ".")
    normalized = normalized.strip("-._")
    if not normalized:
        normalized = "file"
    if len(normalized) > max_length:
        normalized = normalized[:max_length]
    return normalized


def generate_run_id(prefix: str = "run") -> str:
    epoch_ms = int(time.time() * 1000)
    random_bits = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
    return f"{prefix}-{epoch_ms}-{random_bits}"


def ensure_run_paths(config: AppConfig, run_id: str) -> RunPaths:
    base = config.runtime.output_dir / run_id
    assets = base / "assets"
    base.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        run_id=run_id,
        base_dir=base,
        output_file=base / "output.md",
        assets_dir=assets,
        log_file=base / config.runtime.log_file,
    )


def atomic_write(path: Path, data: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding=encoding) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, path)


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent) as tmp:
        tmp_path = Path(tmp.name)
    shutil.copy2(source, tmp_path)
    os.replace(tmp_path, destination)


@contextmanager
def temporary_workdir(path: Path) -> Iterator[None]:
    original = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(original)


def iter_files(paths: Iterable[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            for file_path in sorted(path.rglob("*")):
                if file_path.is_file():
                    yield file_path


def size_within_limit(path: Path, max_mb: int) -> bool:
    return path.stat().st_size <= max_mb * 1024 * 1024


def normalize_newlines(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
