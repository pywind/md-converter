from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Literal

from concurrent.futures import Future, ThreadPoolExecutor

from .config import AppConfig
from .core import ConversionError, ConversionOptions, ConversionResult, ConversionService
from .utils import RunPaths, atomic_copy, atomic_write, ensure_run_paths, generate_run_id, slugify


ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime(ISO_FORMAT)


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    EXPIRED = "expired"


@dataclass(slots=True)
class JobArtifacts:
    output_md_path: str | None = None
    assets_dir_path: str | None = None
    run_dir_path: str | None = None
    output_zip_path: str | None = None
    size_bytes_md: int = 0
    size_bytes_assets_total: int = 0


@dataclass(slots=True)
class JobOptions:
    image_policy: Literal["extract", "ignore"] = "extract"
    size_limit_mb: int | None = None
    timeout_s: int | None = None
    normalize_headings: bool = True
    output_mode: Literal["md", "zip", "both"] = "md"
    dedupe: bool = False

    def to_conversion_options(self) -> ConversionOptions:
        return ConversionOptions(
            size_limit_mb=self.size_limit_mb,
            timeout_s=self.timeout_s,
            image_policy=self.image_policy,
            normalize_headings=self.normalize_headings,
            output_mode=self.output_mode,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "image_policy": self.image_policy,
            "size_limit_mb": self.size_limit_mb,
            "timeout_s": self.timeout_s,
            "normalize_headings": self.normalize_headings,
            "output_mode": self.output_mode,
        }

    def signature(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class JobRecord:
    job_id: str
    status: JobStatus
    progress: float = 0.0
    submitted_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    artifacts: JobArtifacts | None = None
    options: dict[str, object] = field(default_factory=dict)
    parent_job_id: str | None = None
    reused: bool = False
    input_hash: str | None = None

    def to_payload(self) -> dict[str, object | None]:
        payload = asdict(self)
        payload["status"] = self.status.value
        if self.artifacts is not None:
            payload["artifacts"] = asdict(self.artifacts)
        return payload


class JobStore:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._root = config.runtime.output_dir
        self._index_dir = self._root / "_index"
        self._jobs_index = self._index_dir / "jobs.jsonl"
        self._latest_file = self._index_dir / "latest.json"
        self._dedupe_file = self._index_dir / "dedupe.json"
        self._status_archive = self._index_dir / "status"
        self._input_cache = self._index_dir / "inputs"
        self._lock = threading.Lock()
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._status_archive.mkdir(parents=True, exist_ok=True)
        self._input_cache.mkdir(parents=True, exist_ok=True)

    def run_paths(self, job_id: str) -> RunPaths:
        return ensure_run_paths(self._config, job_id)

    def status_path(self, job_id: str) -> Path:
        return self._root / job_id / "status.json"

    def lock_path(self, job_id: str) -> Path:
        return self._root / job_id / ".lock"

    def archive_status_path(self, job_id: str) -> Path:
        return self._status_archive / f"{job_id}.json"

    def write_status(self, record: JobRecord, *, archive: bool = False) -> None:
        path = self.archive_status_path(record.job_id) if archive else self.status_path(record.job_id)
        payload = json.dumps(record.to_payload(), indent=2)
        atomic_write(path, payload)

    def read_status(self, job_id: str) -> JobRecord | None:
        for candidate in (self.status_path(job_id), self.archive_status_path(job_id)):
            if candidate.exists():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return self._record_from_dict(data)
        return None

    def append_index(self, record: JobRecord) -> None:
        payload = json.dumps(record.to_payload())
        with self._lock:
            with self._jobs_index.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
            latest = self._load_latest()
            latest.append(record.to_payload())
            latest = latest[-200:]
            atomic_write(self._latest_file, json.dumps(latest, indent=2))

    def _load_latest(self) -> list[dict[str, object]]:
        if not self._latest_file.exists():
            return []
        try:
            return json.loads(self._latest_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def list_latest(self, limit: int = 50) -> list[dict[str, object]]:
        latest = self._load_latest()
        if limit <= 0:
            return latest
        return latest[-limit:]

    def cache_input(self, digest: str, data: bytes) -> Path:
        path = self._input_cache / digest
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            if tmp.exists():
                tmp.unlink()
            tmp.write_bytes(data)
            tmp.replace(path)
        return path

    def cache_input_from_path(self, digest: str, source: Path) -> Path:
        path = self._input_cache / digest
        if not path.exists() and source.exists():
            atomic_copy(source, path)
        return path

    def get_cached_input(self, digest: str) -> Path | None:
        path = self._input_cache / digest
        if path.exists():
            return path
        return None

    def record_dedupe(self, key: str, job_id: str) -> None:
        with self._lock:
            mapping = self._load_dedupe()
            mapping[key] = job_id
            atomic_write(self._dedupe_file, json.dumps(mapping, indent=2))

    def lookup_dedupe(self, key: str) -> str | None:
        mapping = self._load_dedupe()
        return mapping.get(key)

    def _load_dedupe(self) -> dict[str, str]:
        if not self._dedupe_file.exists():
            return {}
        try:
            data = json.loads(self._dedupe_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        return {}

    def write_summary(self, job_id: str, payload: dict[str, object]) -> None:
        path = self._root / job_id / "summary.json"
        atomic_write(path, json.dumps(payload, indent=2))

    def _record_from_dict(self, data: dict[str, object]) -> JobRecord:
        status = JobStatus(str(data.get("status", JobStatus.QUEUED.value)))
        artifacts_dict = data.get("artifacts")
        artifacts = None
        if isinstance(artifacts_dict, dict):
            artifacts = JobArtifacts(
                output_md_path=str(artifacts_dict.get("output_md_path")) if artifacts_dict.get("output_md_path") else None,
                assets_dir_path=str(artifacts_dict.get("assets_dir_path")) if artifacts_dict.get("assets_dir_path") else None,
                run_dir_path=str(artifacts_dict.get("run_dir_path")) if artifacts_dict.get("run_dir_path") else None,
                output_zip_path=str(artifacts_dict.get("output_zip_path")) if artifacts_dict.get("output_zip_path") else None,
                size_bytes_md=int(artifacts_dict.get("size_bytes_md", 0)),
                size_bytes_assets_total=int(artifacts_dict.get("size_bytes_assets_total", 0)),
            )
        warnings_value = data.get("warnings")
        if isinstance(warnings_value, list):
            warnings = [str(item) for item in warnings_value]
        else:
            warnings = []
        return JobRecord(
            job_id=str(data.get("job_id")),
            status=status,
            progress=float(data.get("progress", 0.0)),
            submitted_at=str(data.get("submitted_at")) if data.get("submitted_at") else None,
            started_at=str(data.get("started_at")) if data.get("started_at") else None,
            finished_at=str(data.get("finished_at")) if data.get("finished_at") else None,
            warnings=warnings,
            error_code=str(data.get("error_code")) if data.get("error_code") else None,
            error_message=str(data.get("error_message")) if data.get("error_message") else None,
            artifacts=artifacts,
            options=dict(data.get("options", {})) if isinstance(data.get("options"), dict) else {},
            parent_job_id=str(data.get("parent_job_id")) if data.get("parent_job_id") else None,
            reused=bool(data.get("reused", False)),
            input_hash=str(data.get("input_hash")) if data.get("input_hash") else None,
        )


@dataclass(slots=True)
class JobHandle:
    job_id: str
    filename: str
    source_path: Path
    options: JobOptions
    parent_job_id: str | None
    cancel_event: threading.Event
    submitted_at: datetime
    input_hash: str


class JobManager:
    def __init__(self, config: AppConfig, service: ConversionService) -> None:
        self._config = config
        self._service = service
        self._store = JobStore(config)
        pool_size = config.runtime.jobs.worker_pool_size
        if pool_size <= 0:
            pool_size = min(4, max(1, os.cpu_count() or 1))
        self._executor = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="job-worker")
        self._jobs: dict[str, JobHandle] = {}
        self._futures: dict[str, Future[ConversionResult]] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        self._retention_thread = threading.Thread(target=self._retention_loop, daemon=True)
        self._retention_thread.start()

    def submit(self, filename: str, payload: bytes, options: JobOptions, *, parent_job_id: str | None = None) -> JobRecord:
        submitted = _utc_now()
        job_id = generate_run_id("job")
        sanitized = slugify(filename or "upload")
        run_paths = self._store.run_paths(job_id)
        input_dir = run_paths.base_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        source_path = input_dir / sanitized
        source_path.write_bytes(payload)
        digest = sha256(payload).hexdigest()
        self._store.cache_input(digest, payload)

        options_dict = options.as_dict()
        options_dict["source_filename"] = sanitized
        record = JobRecord(
            job_id=job_id,
            status=JobStatus.QUEUED,
            progress=0.0,
            submitted_at=_iso(submitted),
            options=options_dict,
            parent_job_id=parent_job_id,
            input_hash=digest,
        )
        self._store.write_status(record)
        self._store.append_index(record)

        dedupe_key: str | None = None
        if options.dedupe and self._config.runtime.jobs.dedupe_enabled:
            dedupe_key = sha256((digest + options.signature()).encode("utf-8")).hexdigest()
            existing = self._store.lookup_dedupe(dedupe_key)
            if existing:
                reused = self._attempt_reuse(job_id, existing, options, digest, submitted, sanitized)
                if reused:
                    reused_record = self._store.read_status(job_id)
                    if reused_record:
                        return reused_record
        handle = JobHandle(
            job_id=job_id,
            filename=sanitized,
            source_path=source_path,
            options=options,
            parent_job_id=parent_job_id,
            cancel_event=threading.Event(),
            submitted_at=submitted,
            input_hash=digest,
        )
        with self._lock:
            self._jobs[job_id] = handle
        future = self._executor.submit(self._run_job, handle)
        with self._lock:
            self._futures[job_id] = future
        if dedupe_key:
            self._store.record_dedupe(dedupe_key, job_id)
        return record

    def _attempt_reuse(
        self,
        job_id: str,
        existing_job_id: str,
        options: JobOptions,
        digest: str,
        submitted: datetime,
        filename: str,
    ) -> bool:
        existing = self._store.read_status(existing_job_id)
        if not existing or existing.status is not JobStatus.SUCCEEDED or not existing.artifacts:
            return False
        run_paths = self._store.run_paths(job_id)
        artifacts = existing.artifacts
        if not artifacts.output_md_path:
            return False
        source_output = Path(artifacts.output_md_path)
        if not source_output.exists():
            return False
        atomic_copy(source_output, run_paths.output_file)
        assets_total = 0
        if artifacts.assets_dir_path:
            source_assets = Path(artifacts.assets_dir_path)
            if source_assets.exists():
                for asset in source_assets.rglob("*"):
                    if asset.is_file():
                        destination = run_paths.assets_dir / asset.relative_to(source_assets)
                        atomic_copy(asset, destination)
                        assets_total += destination.stat().st_size
        zip_path: Path | None = None
        if options.output_mode in {"zip", "both"} and artifacts.output_zip_path:
            source_zip = Path(artifacts.output_zip_path)
            if source_zip.exists():
                zip_path = run_paths.base_dir / "output.zip"
                atomic_copy(source_zip, zip_path)
        finished = _utc_now()
        options_dict = options.as_dict()
        options_dict["source_filename"] = filename
        reused_record = JobRecord(
            job_id=job_id,
            status=JobStatus.SUCCEEDED,
            progress=1.0,
            submitted_at=_iso(submitted),
            started_at=_iso(submitted),
            finished_at=_iso(finished),
            warnings=existing.warnings,
            artifacts=JobArtifacts(
                output_md_path=str(run_paths.output_file),
                assets_dir_path=str(run_paths.assets_dir),
                run_dir_path=str(run_paths.base_dir),
                output_zip_path=str(zip_path) if zip_path else None,
                size_bytes_md=run_paths.output_file.stat().st_size if run_paths.output_file.exists() else 0,
                size_bytes_assets_total=assets_total,
            ),
            options=options_dict,
            parent_job_id=existing_job_id,
            reused=True,
            input_hash=digest,
        )
        self._store.write_status(reused_record)
        self._store.append_index(reused_record)
        self._store.write_summary(
            job_id,
            {
                "job_id": job_id,
                "status": JobStatus.SUCCEEDED.value,
                "reused": True,
                "source_job_id": existing_job_id,
                "duration_seconds": 0.0,
            },
        )
        return True

    def _run_job(self, handle: JobHandle) -> ConversionResult | None:
        try:
            return self._execute_job(handle)
        finally:
            self._finalize_job(handle.job_id)

    def _execute_job(self, handle: JobHandle) -> ConversionResult | None:
        record = self._store.read_status(handle.job_id)
        if record is None:
            record = JobRecord(job_id=handle.job_id, status=JobStatus.QUEUED)
        if handle.cancel_event.is_set():
            self._update_status(handle.job_id, JobStatus.CANCELED, progress=0.0)
            return None
        started = _utc_now()
        self._update_status(
            handle.job_id,
            JobStatus.RUNNING,
            progress=0.0,
            started_at=_iso(started),
        )
        lock_path = self._store.lock_path(handle.job_id)
        lock_path.write_text(str(started.timestamp()), encoding="utf-8")

        def _progress(value: float) -> None:
            self._update_status(handle.job_id, JobStatus.RUNNING, progress=value)

        try:
            result = self._service.convert_file(
                handle.source_path,
                run_id=handle.job_id,
                options=handle.options.to_conversion_options(),
                progress=_progress,
                cancellation=handle.cancel_event,
            )
        except ConversionError as exc:
            finished = _utc_now()
            status = JobStatus.CANCELED if exc.code == "CANCELED" else JobStatus.FAILED
            self._update_status(
                handle.job_id,
                status,
                progress=1.0 if status is JobStatus.CANCELED else max(record.progress, 0.0),
                finished_at=_iso(finished),
                warnings=[],
                error_code=exc.code,
                error_message=str(exc),
            )
            self._store.write_summary(
                handle.job_id,
                {
                    "job_id": handle.job_id,
                    "status": status.value,
                    "error_code": exc.code,
                    "duration_seconds": (finished - started).total_seconds(),
                },
            )
            if status is JobStatus.CANCELED and not self._config.runtime.jobs.keep_partials:
                self._cleanup_artifacts(handle.job_id)
            lock_path.unlink(missing_ok=True)
            self._append_terminal(handle.job_id)
            return None
        except Exception as exc:  # pragma: no cover - unexpected paths
            finished = _utc_now()
            self._update_status(
                handle.job_id,
                JobStatus.FAILED,
                progress=0.0,
                finished_at=_iso(finished),
                error_code="UNKNOWN",
                error_message=str(exc),
            )
            self._store.write_summary(
                handle.job_id,
                {
                    "job_id": handle.job_id,
                    "status": JobStatus.FAILED.value,
                    "error_code": "UNKNOWN",
                    "duration_seconds": (finished - started).total_seconds(),
                },
            )
            lock_path.unlink(missing_ok=True)
            self._append_terminal(handle.job_id)
            raise

        finished = _utc_now()
        artifacts = self._build_artifacts(handle.job_id, result)
        self._update_status(
            handle.job_id,
            JobStatus.SUCCEEDED,
            progress=1.0,
            finished_at=_iso(finished),
            warnings=result.warnings,
            artifacts=artifacts,
            reused=result.reused,
        )
        self._store.write_summary(
            handle.job_id,
            {
                "job_id": handle.job_id,
                "status": JobStatus.SUCCEEDED.value,
                "duration_seconds": (finished - started).total_seconds(),
                "warnings": result.warnings,
                "input_hash": handle.input_hash,
            },
        )
        lock_path.unlink(missing_ok=True)
        self._append_terminal(handle.job_id)
        return result

    def _finalize_job(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._futures.pop(job_id, None)

    def _build_artifacts(self, job_id: str, result: ConversionResult) -> JobArtifacts:
        assets_total = 0
        if result.assets_dir.exists():
            for item in result.assets_dir.rglob("*"):
                if item.is_file():
                    assets_total += item.stat().st_size
        zip_path = result.zip_path
        return JobArtifacts(
            output_md_path=str(result.output_path.resolve()),
            assets_dir_path=str(result.assets_dir.resolve()),
            run_dir_path=str(result.output_path.parent.resolve()),
            output_zip_path=str(zip_path.resolve()) if zip_path else None,
            size_bytes_md=result.output_path.stat().st_size if result.output_path.exists() else 0,
            size_bytes_assets_total=assets_total,
        )

    def _cleanup_artifacts(self, job_id: str) -> None:
        run_dir = self._config.runtime.output_dir / job_id
        if not run_dir.exists():
            return
        for child in run_dir.iterdir():
            if child.name == "status.json":
                continue
            if child.is_dir():
                for item in child.rglob("*"):
                    if item.is_file():
                        item.unlink(missing_ok=True)
                child.rmdir()
            else:
                child.unlink(missing_ok=True)

    def _update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        progress: float | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        warnings: list[str] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        artifacts: JobArtifacts | None = None,
        reused: bool | None = None,
    ) -> None:
        record = self._store.read_status(job_id) or JobRecord(job_id=job_id, status=status)
        record.status = status
        if progress is not None:
            record.progress = max(record.progress, min(progress, 1.0))
        if started_at:
            record.started_at = started_at
        if finished_at:
            record.finished_at = finished_at
        if warnings is not None:
            record.warnings = warnings
        if error_code is not None:
            record.error_code = error_code
        if error_message is not None:
            record.error_message = error_message
        if artifacts is not None:
            record.artifacts = artifacts
        if reused is not None:
            record.reused = reused
        self._store.write_status(record)

    def _append_terminal(self, job_id: str) -> None:
        record = self._store.read_status(job_id)
        if record:
            self._store.append_index(record)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            handle = self._jobs.get(job_id)
        if not handle:
            record = self._store.read_status(job_id)
            if record and record.status is JobStatus.QUEUED:
                record.status = JobStatus.CANCELED
                record.finished_at = _iso(_utc_now())
                record.progress = 0.0
                self._store.write_status(record)
                self._append_terminal(job_id)
                return True
            return False
        handle.cancel_event.set()
        self._update_status(job_id, JobStatus.CANCELED)
        self._append_terminal(job_id)
        return True

    def retry(self, job_id: str) -> JobRecord | None:
        record = self._store.read_status(job_id)
        if not record:
            return None
        if record.status not in {JobStatus.FAILED, JobStatus.CANCELED, JobStatus.EXPIRED}:
            return None
        if not record.input_hash:
            return None
        cached = self._store.get_cached_input(record.input_hash)
        if cached is None or not cached.exists():
            return None
        payload = cached.read_bytes()
        opts = record.options
        job_options = JobOptions(
            image_policy=str(opts.get("image_policy", "extract")),
            size_limit_mb=int(opts.get("size_limit_mb")) if opts.get("size_limit_mb") is not None else None,
            timeout_s=int(opts.get("timeout_s")) if opts.get("timeout_s") is not None else None,
            normalize_headings=bool(opts.get("normalize_headings", True)),
            output_mode=str(opts.get("output_mode", "md")),
            dedupe=False,
        )
        filename = str(opts.get("source_filename") or "retry")
        return self.submit(filename, payload, job_options, parent_job_id=job_id)

    def get_status(self, job_id: str) -> JobRecord | None:
        return self._store.read_status(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict[str, object]]:
        return self._store.list_latest(limit)

    def expire_stale_jobs(self) -> None:
        retention_days = self._config.runtime.jobs.retention_days
        if retention_days <= 0:
            return
        if not self._config.runtime.output_dir.exists():
            return
        cutoff = time.time() - retention_days * 86400
        for run_dir in self._config.runtime.output_dir.iterdir():
            if not run_dir.is_dir() or run_dir.name.startswith("_"):
                continue
            status = self._store.read_status(run_dir.name)
            if not status or status.status in {JobStatus.RUNNING, JobStatus.QUEUED}:
                continue
            finished = status.finished_at
            if not finished:
                continue
            try:
                finished_ts = datetime.strptime(finished, ISO_FORMAT).timestamp()
            except ValueError:
                continue
            if finished_ts < cutoff and status.status is not JobStatus.EXPIRED:
                status.status = JobStatus.EXPIRED
                status.progress = 1.0
                status.finished_at = status.finished_at or _iso(_utc_now())
                self._store.write_status(status, archive=True)
                for child in run_dir.iterdir():
                    if child.is_dir():
                        for item in child.rglob("*"):
                            if item.is_file():
                                item.unlink(missing_ok=True)
                        child.rmdir()
                    else:
                        child.unlink(missing_ok=True)
                run_dir.rmdir()
                self._append_terminal(status.job_id)

    def _retention_loop(self) -> None:  # pragma: no cover - background thread timing
        while not self._shutdown:
            try:
                self.expire_stale_jobs()
            except Exception:
                pass
            time.sleep(3600)

    def shutdown(self) -> None:
        self._shutdown = True
        self._executor.shutdown(wait=False)


__all__ = [
    "JobManager",
    "JobOptions",
    "JobRecord",
    "JobStatus",
    "JobArtifacts",
]

