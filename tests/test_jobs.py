from __future__ import annotations

import time
from pathlib import Path

from core.markdown_converter.config import AppConfig, RuntimeConfig
from core.markdown_converter.core import ConversionService
from core.markdown_converter.jobs import JobManager, JobOptions, JobStatus


def build_manager(tmp_path: Path) -> JobManager:
    runtime = RuntimeConfig(output_dir=tmp_path, enable_local_api=True)
    runtime.jobs.worker_pool_size = 1
    runtime.jobs.dedupe_enabled = True
    config = AppConfig(runtime=runtime)
    service = ConversionService(config)
    return JobManager(config, service)


def wait_for_status(manager: JobManager, job_id: str, status: JobStatus) -> None:
    for _ in range(200):
        record = manager.get_status(job_id)
        if record and record.status is status:
            return
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not reach {status}")


def test_job_manager_completes_and_tracks_artifacts(tmp_path):
    manager = build_manager(tmp_path)
    try:
        options = JobOptions(output_mode="both")
        record = manager.submit("note.txt", b"hello world", options)
        wait_for_status(manager, record.job_id, JobStatus.SUCCEEDED)
        final = manager.get_status(record.job_id)
        assert final is not None
        assert final.progress == 1.0
        assert final.artifacts is not None
        output_path = Path(final.artifacts.output_md_path)
        assert output_path.exists()
        if final.artifacts.output_zip_path:
            assert Path(final.artifacts.output_zip_path).exists()
    finally:
        manager.shutdown()


def test_job_manager_dedupe_reuses_artifacts(tmp_path):
    manager = build_manager(tmp_path)
    try:
        first = manager.submit("report.txt", b"reuse me", JobOptions(output_mode="both", dedupe=True))
        wait_for_status(manager, first.job_id, JobStatus.SUCCEEDED)
        deduped = manager.submit("report.txt", b"reuse me", JobOptions(output_mode="both", dedupe=True))
        assert deduped.status is JobStatus.SUCCEEDED
        assert deduped.reused is True
        assert deduped.artifacts is not None
        assert Path(deduped.artifacts.output_md_path).exists()
    finally:
        manager.shutdown()


def test_job_manager_retry_failed_job(tmp_path):
    manager = build_manager(tmp_path)
    try:
        failure = manager.submit("data.bin", b"\x00\x01", JobOptions())
        wait_for_status(manager, failure.job_id, JobStatus.FAILED)
        retried = manager.retry(failure.job_id)
        assert retried is not None
        assert retried.parent_job_id == failure.job_id
    finally:
        manager.shutdown()

