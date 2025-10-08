from __future__ import annotations

import concurrent.futures
import csv
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Literal, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

ProgressCallback = Callable[[float], None]

from .adapters import AdapterResponse, get_adapter
from .config import AppConfig
from .detection import DetectionError, detect_document_type
from .logging import BatchSummary, RunLogEntry, RunLogger, StageTimings, write_summary_csv
from .utils import RunPaths, ensure_run_paths, generate_run_id, iter_files, normalize_newlines, size_within_limit


class ConversionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class ConversionOptions:
    size_limit_mb: int | None = None
    timeout_s: int | None = None
    image_policy: Literal["extract", "ignore"] = "extract"
    normalize_headings: bool = True
    output_mode: Literal["md", "zip", "both"] = "md"


@dataclass(slots=True)
class ConversionResult:
    run_id: str
    output_path: Path
    assets_dir: Path
    warnings: list[str]
    summary: str
    zip_path: Path | None = None
    reused: bool = False


@dataclass(slots=True)
class BatchConversionResult:
    runs: list[ConversionResult]
    summary: BatchSummary


class ConversionService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def convert_file(
        self,
        path: Path,
        *,
        run_id: str | None = None,
        options: ConversionOptions | None = None,
        progress: ProgressCallback | None = None,
        cancellation: Event | None = None,
        reused: bool = False,
    ) -> ConversionResult:
        opts = options or ConversionOptions()
        callback = progress or (lambda _: None)
        run_id = run_id or generate_run_id()
        run_paths = ensure_run_paths(self._config, run_id)
        logger = RunLogger(run_paths.log_file)
        start = time.perf_counter()
        deadline = None
        if opts.timeout_s is not None:
            deadline = start + float(opts.timeout_s)
        base_timeout = self._config.runtime.convert_timeout_s
        if deadline is None:
            deadline = start + float(base_timeout)
        else:
            deadline = min(deadline, start + float(base_timeout))

        callback(0.0)
        try:
            response = self._convert_internal(
                path,
                run_paths,
                logger,
                opts,
                callback,
                cancellation,
                deadline,
            )
        except ConversionError as exc:
            size_bytes = path.stat().st_size if path.exists() else 0
            logger.append(
                RunLogEntry(
                    run_id=run_id,
                    source=str(path),
                    status="failure",
                    mime_type="unknown",
                    warnings=[],
                    error_code=exc.code,
                    timings=StageTimings(0, 0, 0, 0),
                    output_path=str(run_paths.output_file),
                    assets=[],
                    size_bytes=size_bytes,
                )
            )
            raise

        elapsed = time.perf_counter() - start
        summary = f"Converted {path.name} -> {run_paths.output_file} in {elapsed:.2f}s"
        zip_path: Path | None = None
        if opts.output_mode in {"zip", "both"}:
            zip_path = self._create_zip(run_paths)
        callback(1.0)
        return ConversionResult(
            run_id=run_id,
            output_path=run_paths.output_file,
            assets_dir=run_paths.assets_dir,
            warnings=response.warnings,
            summary=summary,
            zip_path=zip_path,
            reused=reused,
        )

    def _convert_internal(
        self,
        path: Path,
        run_paths: RunPaths,
        logger: RunLogger,
        options: ConversionOptions,
        progress: ProgressCallback,
        cancellation: Event | None,
        deadline: float,
    ) -> AdapterResponse:
        def _ensure_not_cancelled(stage: str) -> None:
            if cancellation is not None and cancellation.is_set():
                raise ConversionError("CANCELED", f"Job canceled during {stage}")

        _ensure_not_cancelled("initialization")
        read_start = time.perf_counter()
        if not path.exists():
            raise ConversionError("NOT_FOUND", f"Source file does not exist: {path}")
        effective_limit = self._effective_size_limit(options)
        if not size_within_limit(path, effective_limit):
            raise ConversionError("SIZE_LIMIT", f"File exceeds configured limit: {path.name}")
        size_bytes = path.stat().st_size
        read_elapsed = (time.perf_counter() - read_start) * 1000
        progress(0.1)

        _ensure_not_cancelled("detection")
        detect_start = time.perf_counter()
        try:
            detection = detect_document_type(path)
        except DetectionError as exc:
            raise ConversionError("UNSUPPORTED_MIME", str(exc)) from exc
        detect_elapsed = (time.perf_counter() - detect_start) * 1000
        progress(0.2)

        try:
            adapter = get_adapter(detection.document_type)
        except KeyError as exc:
            raise ConversionError("NO_ADAPTER", f"No adapter for {detection.document_type.value}") from exc

        _ensure_not_cancelled("conversion")
        convert_start = time.perf_counter()
        response = adapter.convert(path, run_paths.assets_dir)
        convert_elapsed = (time.perf_counter() - convert_start) * 1000
        if time.perf_counter() > deadline:
            raise ConversionError("TIMEOUT", f"Conversion exceeded allotted time for {path.name}")
        progress(0.6)
        _ensure_not_cancelled("post-conversion")

        assets: dict[str, Path] = dict(response.assets)
        if options.image_policy == "ignore":
            for asset_path in assets.values():
                asset_path.unlink(missing_ok=True)
            assets = {}

        progress(0.8)
        _ensure_not_cancelled("finalize")

        markdown = response.markdown
        if options.normalize_headings:
            markdown = self._normalize_headings(markdown)
        markdown = normalize_newlines(markdown)
        for asset_name in assets:
            if f"./assets/{asset_name}" not in markdown:
                markdown += f"\n![{asset_name}](./assets/{asset_name})\n"

        write_start = time.perf_counter()
        from .utils import atomic_write

        atomic_write(run_paths.output_file, markdown)
        write_elapsed = (time.perf_counter() - write_start) * 1000
        if time.perf_counter() > deadline:
            raise ConversionError("TIMEOUT", f"Conversion exceeded allotted time for {path.name}")

        logger.append(
            RunLogEntry(
                run_id=run_paths.run_id,
                source=str(path),
                status="success",
                mime_type=detection.mime_type,
                warnings=response.warnings,
                error_code=None,
                timings=StageTimings(
                    read_ms=read_elapsed,
                    detect_ms=detect_elapsed,
                    convert_ms=convert_elapsed,
                    write_ms=write_elapsed,
                ),
                output_path=str(run_paths.output_file),
                assets=[str(p) for p in assets.values()],
                size_bytes=size_bytes,
            )
        )
        return AdapterResponse(markdown=markdown, warnings=response.warnings, assets=assets)

    def _normalize_headings(self, markdown: str) -> str:
        normalized: list[str] = []
        for line in markdown.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                level = max(1, min(level, 6))
                content = stripped[level:].strip()
                normalized.append(("#" * level) + (f" {content}" if content else ""))
            else:
                normalized.append(line.rstrip())
        return "\n".join(normalized)

    def _effective_size_limit(self, options: ConversionOptions) -> int:
        limit = self._config.runtime.max_file_size_mb
        candidate = options.size_limit_mb
        if candidate is not None and candidate > 0:
            limit = min(limit, candidate)
        return max(1, limit)

    def _create_zip(self, run_paths: RunPaths) -> Path:
        zip_path = run_paths.base_dir / "output.zip"
        files: list[Path] = []
        if run_paths.output_file.exists():
            files.append(run_paths.output_file)
        if run_paths.assets_dir.exists():
            for asset in sorted(run_paths.assets_dir.rglob("*")):
                if asset.is_file():
                    files.append(asset)
        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
            for file_path in files:
                relative = file_path.relative_to(run_paths.base_dir)
                if ".." in relative.parts:
                    continue
                archive.write(file_path, relative.as_posix())
        return zip_path

    def batch_convert(
        self,
        inputs: Sequence[Path],
        *,
        parallelism: int | None = None,
        single_run: bool = False,
    ) -> BatchConversionResult:
        paths = list(iter_files(inputs))
        summary = BatchSummary()
        results: list[ConversionResult] = []
        parallelism = parallelism or self._config.runtime.batch.default_parallelism
        parallelism = max(1, parallelism)

        if single_run:
            run_id = generate_run_id("batch")
            run_paths = ensure_run_paths(self._config, run_id)
            logger = RunLogger(run_paths.log_file)
            combined_markdown: list[str] = []
            warnings: list[str] = []
            for path in paths:
                try:
                    response = self._convert_internal(path, run_paths, logger)
                    combined_markdown.append(f"# {path.name}\n\n{response.markdown}\n")
                    warnings.extend(response.warnings)
                    summary.successes += 1
                except ConversionError as exc:
                    summary.failures += 1
                    logger.append(
                        RunLogEntry(
                            run_id=run_paths.run_id,
                            source=str(path),
                            status="failure",
                            mime_type="unknown",
                            warnings=[],
                            error_code=exc.code,
                            timings=StageTimings(0, 0, 0, 0),
                            output_path=str(run_paths.output_file),
                            assets=[],
                            size_bytes=path.stat().st_size if path.exists() else 0,
                        )
                    )
            from .utils import atomic_write

            atomic_write(run_paths.output_file, normalize_newlines("\n".join(combined_markdown)))
            results.append(
                ConversionResult(
                    run_id=run_id,
                    output_path=run_paths.output_file,
                    assets_dir=run_paths.assets_dir,
                    warnings=warnings,
                    summary=f"Batch converted {len(paths)} files into {run_paths.output_file}",
                )
            )
        else:
            if parallelism == 1:
                for path in paths:
                    try:
                        result = self.convert_file(path)
                        results.append(result)
                        summary.successes += 1
                    except ConversionError:
                        summary.failures += 1
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as executor:
                    future_map = {executor.submit(self.convert_file, path): path for path in paths}
                    for future in concurrent.futures.as_completed(future_map):
                        path = future_map[future]
                        try:
                            result = future.result()
                            results.append(result)
                            summary.successes += 1
                        except ConversionError:
                            summary.failures += 1
        summary.total = len(paths)
        for result in results:
            for warning in result.warnings:
                summary.warnings[warning] = summary.warnings.get(warning, 0) + 1

        if paths:
            summary_path = self._config.runtime.output_dir / self._config.runtime.summary_csv
            default_header = [
                "batch_id",
                "timestamp",
                "total",
                "successes",
                "failures",
                "warnings",
            ]
            if summary_path.exists():
                with summary_path.open("r", encoding="utf-8", newline="") as handle:
                    reader = list(csv.reader(handle))
                if reader:
                    header = reader[0]
                    rows = reader[1:]
                else:
                    header = default_header
                    rows = []
            else:
                header = default_header
                rows = []
            batch_id = generate_run_id("batch")
            rows.append(summary.as_row(batch_id))
            write_summary_csv(summary_path, header, rows)
        return BatchConversionResult(runs=results, summary=summary)


__all__ = [
    "ConversionService",
    "ConversionResult",
    "ConversionOptions",
    "ConversionError",
    "BatchConversionResult",
]
