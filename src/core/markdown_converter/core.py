from __future__ import annotations

import concurrent.futures
import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

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
class ConversionResult:
    run_id: str
    output_path: Path
    assets_dir: Path
    warnings: list[str]
    summary: str


@dataclass(slots=True)
class BatchConversionResult:
    runs: list[ConversionResult]
    summary: BatchSummary


class ConversionService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def convert_file(self, path: Path) -> ConversionResult:
        run_id = generate_run_id()
        run_paths = ensure_run_paths(self._config, run_id)
        logger = RunLogger(run_paths.log_file)
        start = time.perf_counter()
        try:
            result = self._convert_internal(path, run_paths, logger)
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
        return ConversionResult(
            run_id=run_id,
            output_path=run_paths.output_file,
            assets_dir=run_paths.assets_dir,
            warnings=result.warnings,
            summary=summary,
        )

    def _convert_internal(self, path: Path, run_paths: RunPaths, logger: RunLogger) -> AdapterResponse:
        read_start = time.perf_counter()
        if not path.exists():
            raise ConversionError("NOT_FOUND", f"Source file does not exist: {path}")
        if not size_within_limit(path, self._config.runtime.max_file_size_mb):
            raise ConversionError("SIZE_LIMIT", f"File exceeds configured limit: {path.name}")
        size_bytes = path.stat().st_size
        read_elapsed = (time.perf_counter() - read_start) * 1000

        detect_start = time.perf_counter()
        try:
            detection = detect_document_type(path)
        except DetectionError as exc:
            raise ConversionError("UNSUPPORTED_MIME", str(exc)) from exc
        detect_elapsed = (time.perf_counter() - detect_start) * 1000

        try:
            adapter = get_adapter(detection.document_type)
        except KeyError as exc:
            raise ConversionError("NO_ADAPTER", f"No adapter for {detection.document_type.value}") from exc

        convert_start = time.perf_counter()
        response = adapter.convert(path, run_paths.assets_dir)
        convert_elapsed = (time.perf_counter() - convert_start) * 1000
        if convert_elapsed > self._config.runtime.convert_timeout_s * 1000:
            raise ConversionError(
                "TIMEOUT",
                f"Conversion exceeded {self._config.runtime.convert_timeout_s}s for {path.name}",
            )

        write_start = time.perf_counter()
        markdown = response.markdown
        if not markdown.endswith("\n"):
            markdown += "\n"
        for asset_name in response.assets:
            # ensure relative paths exist in markdown
            if f"./assets/{asset_name}" not in markdown:
                markdown += f"\n![{asset_name}](./assets/{asset_name})\n"
        from .utils import atomic_write

        atomic_write(run_paths.output_file, markdown)
        # propagate any markdown mutations (e.g., appended asset links) to the
        # response object so callers aggregating the response body do not lose
        # the references written to disk.
        response.markdown = markdown
        write_elapsed = (time.perf_counter() - write_start) * 1000

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
                assets=[str(p) for p in response.assets.values()],
                size_bytes=size_bytes,
            )
        )
        return response

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


__all__ = ["ConversionService", "ConversionResult", "ConversionError", "BatchConversionResult"]
