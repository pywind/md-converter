from __future__ import annotations

import concurrent.futures
import csv
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

ProgressCallback = Callable[[float], None]

from .adapters import AdapterResponse, get_adapter
from .config import AppConfig
from .detection import DetectionError, detect_document_type
from .logging import BatchSummary, RunLogEntry, RunLogger, StageTimings, write_summary_csv
from .models import BatchConversionResult, ConversionOptions, ConversionResult
from .utils import (
    RunPaths,
    atomic_write,
    ensure_run_paths,
    generate_run_id,
    iter_files,
    normalize_newlines,
    size_within_limit,
)


class ConversionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class _ConversionContext:
    run_id: str
    run_paths: RunPaths
    logger: RunLogger
    options: ConversionOptions
    callback: ProgressCallback
    cancellation: Event | None
    deadline: float


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
        context = self._build_context(
            run_id=run_id,
            run_paths=run_paths,
            logger=logger,
            options=opts,
            callback=callback,
            cancellation=cancellation,
            start=start,
        )

        callback(0.0)
        try:
            response = self._convert_internal(path, context)
        except ConversionError as exc:
            self._log_failure(path, context, exc)
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

    def _convert_internal(self, path: Path, context: _ConversionContext) -> AdapterResponse:
        self._ensure_not_cancelled(context, "initialization")
        size_bytes, read_elapsed = self._validate_source(path, context.options)
        context.callback(0.1)

        self._ensure_not_cancelled(context, "detection")
        detection, detect_elapsed = self._detect_document(path)
        context.callback(0.2)

        adapter = self._get_adapter(detection.document_type)
        self._ensure_not_cancelled(context, "conversion")
        response, convert_elapsed = self._run_adapter(adapter, path, context)
        context.callback(0.6)

        assets = self._prepare_assets(response.assets, context.options)
        context.callback(0.8)

        self._ensure_not_cancelled(context, "finalize")
        markdown = self._finalize_markdown(response.markdown, assets, context.options)
        self._ensure_not_cancelled(context, "write")
        write_elapsed = self._write_output(context.run_paths.output_file, markdown, context)

        self._append_success_log(
            context,
            path,
            detection.mime_type,
            response.warnings,
            assets,
            size_bytes,
            StageTimings(
                read_ms=read_elapsed,
                detect_ms=detect_elapsed,
                convert_ms=convert_elapsed,
                write_ms=write_elapsed,
            ),
        )
        return AdapterResponse(markdown=markdown, warnings=response.warnings, assets=assets)

    def _build_context(
        self,
        *,
        run_id: str,
        run_paths: RunPaths,
        logger: RunLogger,
        options: ConversionOptions,
        callback: ProgressCallback,
        cancellation: Event | None,
        start: float,
    ) -> _ConversionContext:
        deadline = self._compute_deadline(start, options)
        return _ConversionContext(
            run_id=run_id,
            run_paths=run_paths,
            logger=logger,
            options=options,
            callback=callback,
            cancellation=cancellation,
            deadline=deadline,
        )

    def _compute_deadline(self, start: float, options: ConversionOptions) -> float:
        base_timeout = float(self._config.runtime.convert_timeout_s)
        candidate = base_timeout
        if options.timeout_s is not None:
            candidate = min(candidate, float(options.timeout_s))
        candidate = max(candidate, 0.0)
        return start + candidate

    def _log_failure(self, path: Path, context: _ConversionContext, exc: ConversionError) -> None:
        size_bytes = path.stat().st_size if path.exists() else 0
        context.logger.append(
            RunLogEntry(
                run_id=context.run_id,
                source=str(path),
                status="failure",
                mime_type="unknown",
                warnings=[],
                error_code=exc.code,
                timings=StageTimings(0, 0, 0, 0),
                output_path=str(context.run_paths.output_file),
                assets=[],
                size_bytes=size_bytes,
            )
        )

    def _ensure_not_cancelled(self, context: _ConversionContext, stage: str) -> None:
        if context.cancellation is not None and context.cancellation.is_set():
            raise ConversionError("CANCELED", f"Job canceled during {stage}")

    def _validate_source(
        self, path: Path, options: ConversionOptions
    ) -> tuple[int, float]:
        read_start = time.perf_counter()
        if not path.exists():
            raise ConversionError("NOT_FOUND", f"Source file does not exist: {path}")
        effective_limit = self._effective_size_limit(options)
        if not size_within_limit(path, effective_limit):
            raise ConversionError("SIZE_LIMIT", f"File exceeds configured limit: {path.name}")
        read_elapsed = (time.perf_counter() - read_start) * 1000
        return path.stat().st_size, read_elapsed

    def _detect_document(self, path: Path):
        detect_start = time.perf_counter()
        try:
            detection = detect_document_type(path)
        except DetectionError as exc:
            raise ConversionError("UNSUPPORTED_MIME", str(exc)) from exc
        detect_elapsed = (time.perf_counter() - detect_start) * 1000
        return detection, detect_elapsed

    def _get_adapter(self, document_type):
        try:
            return get_adapter(document_type)
        except KeyError as exc:
            raise ConversionError("NO_ADAPTER", f"No adapter for {document_type.value}") from exc

    def _run_adapter(
        self, adapter, path: Path, context: _ConversionContext
    ) -> tuple[AdapterResponse, float]:
        convert_start = time.perf_counter()
        response = adapter.convert(path, context.run_paths.assets_dir)
        convert_elapsed = (time.perf_counter() - convert_start) * 1000
        self._ensure_deadline(context, path.name)
        return response, convert_elapsed

    def _prepare_assets(
        self, assets: dict[str, Path], options: ConversionOptions
    ) -> dict[str, Path]:
        prepared = dict(assets)
        if options.image_policy == "ignore":
            for asset_path in prepared.values():
                asset_path.unlink(missing_ok=True)
            return {}
        return prepared

    def _finalize_markdown(
        self, markdown: str, assets: dict[str, Path], options: ConversionOptions
    ) -> str:
        if options.normalize_headings:
            markdown = self._normalize_headings(markdown)
        markdown = normalize_newlines(markdown)
        for asset_name in assets:
            placeholder = f"./assets/{asset_name}"
            if placeholder not in markdown:
                markdown += f"\n![{asset_name}]({placeholder})\n"
        return markdown

    def _write_output(
        self, output_path: Path, markdown: str, context: _ConversionContext
    ) -> float:
        write_start = time.perf_counter()
        atomic_write(output_path, markdown)
        elapsed = (time.perf_counter() - write_start) * 1000
        self._ensure_deadline(context, output_path.name)
        return elapsed

    def _append_success_log(
        self,
        context: _ConversionContext,
        path: Path,
        mime_type: str,
        warnings: list[str],
        assets: dict[str, Path],
        size_bytes: int,
        timings: StageTimings,
    ) -> None:
        context.logger.append(
            RunLogEntry(
                run_id=context.run_id,
                source=str(path),
                status="success",
                mime_type=mime_type,
                warnings=warnings,
                error_code=None,
                timings=timings,
                output_path=str(context.run_paths.output_file),
                assets=[str(p) for p in assets.values()],
                size_bytes=size_bytes,
            )
        )

    def _ensure_deadline(self, context: _ConversionContext, filename: str) -> None:
        if time.perf_counter() > context.deadline:
            raise ConversionError("TIMEOUT", f"Conversion exceeded allotted time for {filename}")

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
        parallelism = max(1, parallelism or self._config.runtime.batch.default_parallelism)

        if single_run and paths:
            result = self._run_single_batch(paths, summary)
            if result:
                results.append(result)
        else:
            results.extend(self._run_multi_batch(paths, summary, parallelism))

        summary.total = len(paths)
        self._accumulate_warnings(results, summary)
        if paths:
            self._write_batch_summary(summary)
        return BatchConversionResult(runs=results, summary=summary)

    def _run_single_batch(self, paths: Sequence[Path], summary: BatchSummary) -> ConversionResult | None:
        run_id = generate_run_id("batch")
        run_paths = ensure_run_paths(self._config, run_id)
        logger = RunLogger(run_paths.log_file)
        combined_markdown: list[str] = []
        warnings: list[str] = []
        for path in paths:
            context = self._build_context(
                run_id=run_id,
                run_paths=run_paths,
                logger=logger,
                options=ConversionOptions(),
                callback=lambda _: None,
                cancellation=None,
                start=time.perf_counter(),
            )
            try:
                response = self._convert_internal(path, context)
            except ConversionError as exc:
                summary.failures += 1
                self._log_failure(path, context, exc)
                continue
            combined_markdown.append(f"# {path.name}\n\n{response.markdown}\n")
            warnings.extend(response.warnings)
            summary.successes += 1

        if not combined_markdown:
            return None

        payload = normalize_newlines("\n".join(combined_markdown))
        atomic_write(run_paths.output_file, payload)
        return ConversionResult(
            run_id=run_id,
            output_path=run_paths.output_file,
            assets_dir=run_paths.assets_dir,
            warnings=warnings,
            summary=f"Batch converted {len(paths)} files into {run_paths.output_file}",
        )

    def _run_multi_batch(
        self, paths: Sequence[Path], summary: BatchSummary, parallelism: int
    ) -> list[ConversionResult]:
        if not paths:
            return []
        if parallelism == 1:
            return self._run_sequential_batch(paths, summary)
        return self._run_parallel_batch(paths, summary, parallelism)

    def _run_sequential_batch(
        self, paths: Sequence[Path], summary: BatchSummary
    ) -> list[ConversionResult]:
        results: list[ConversionResult] = []
        for path in paths:
            try:
                result = self.convert_file(path)
            except ConversionError:
                summary.failures += 1
                continue
            results.append(result)
            summary.successes += 1
        return results

    def _run_parallel_batch(
        self, paths: Sequence[Path], summary: BatchSummary, parallelism: int
    ) -> list[ConversionResult]:
        results: list[ConversionResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as executor:
            future_map = {executor.submit(self.convert_file, path): path for path in paths}
            for future in concurrent.futures.as_completed(future_map):
                path = future_map[future]
                try:
                    result = future.result()
                except ConversionError:
                    summary.failures += 1
                    continue
                results.append(result)
                summary.successes += 1
        return results

    def _accumulate_warnings(self, results: Sequence[ConversionResult], summary: BatchSummary) -> None:
        for result in results:
            for warning in result.warnings:
                summary.warnings[warning] = summary.warnings.get(warning, 0) + 1

    def _write_batch_summary(self, summary: BatchSummary) -> None:
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


__all__ = [
    "ConversionService",
    "ConversionResult",
    "ConversionOptions",
    "ConversionError",
    "BatchConversionResult",
]
