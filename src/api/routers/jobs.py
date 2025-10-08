from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from core.markdown_converter.config import AppConfig
from core.markdown_converter.jobs import JobManager, JobOptions, JobRecord, JobStatus

router = APIRouter(prefix="/api/v1", tags=["jobs"])


def get_config(request: Request) -> AppConfig:
    config = getattr(request.app.state, "config", None)
    if config is None:
        raise HTTPException(status_code=503, detail="CONFIG_UNAVAILABLE")
    return config


def get_manager(request: Request) -> JobManager:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="MANAGER_UNAVAILABLE")
    return manager


@router.post("/jobs", summary="Submit a conversion job", status_code=202)
async def submit_job(
    file: UploadFile = File(...),
    options: str | None = Form(None),
    manager: JobManager = Depends(get_manager),
) -> dict[str, Any]:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="EMPTY_FILE")
    try:
        options_payload = json.loads(options) if options else {}
    except json.JSONDecodeError as exc:  # pragma: no cover - invalid payload path
        raise HTTPException(status_code=400, detail="INVALID_OPTIONS") from exc
    job_options = _build_options(options_payload)
    record = manager.submit(file.filename or "upload", payload, job_options)
    return {
        "job_id": record.job_id,
        "status": record.status.value,
        "submitted_at": record.submitted_at,
        "progress": record.progress,
    }


@router.get("/jobs/{job_id}", summary="Retrieve job status")
def get_job(job_id: str, manager: JobManager = Depends(get_manager)) -> dict[str, Any]:
    record = manager.get_status(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    return _serialize_record(record)


@router.get("/jobs/{job_id}/result", summary="Retrieve job result metadata")
def get_job_result(
    job_id: str,
    as_: str | None = Query(None, alias="as"),
    manager: JobManager = Depends(get_manager),
) -> dict[str, Any]:
    record = manager.get_status(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    if record.status not in {JobStatus.SUCCEEDED, JobStatus.EXPIRED}:
        raise HTTPException(status_code=409, detail="JOB_NOT_READY")
    artifacts = record.artifacts
    if not artifacts:
        raise HTTPException(status_code=404, detail="ARTIFACTS_UNAVAILABLE")
    payload = {
        "job_id": record.job_id,
        "status": record.status.value,
        "artifacts": asdict(artifacts),
        "reused": record.reused,
    }
    if as_ == "zip":
        zip_path = artifacts.output_zip_path
        if not zip_path:
            raise HTTPException(status_code=404, detail="ZIP_UNAVAILABLE")
        payload["zip_path"] = zip_path
    return payload


@router.post("/jobs/{job_id}/cancel", summary="Cancel a queued or running job")
def cancel_job(job_id: str, manager: JobManager = Depends(get_manager)) -> dict[str, Any]:
    if not manager.cancel(job_id):
        raise HTTPException(status_code=409, detail="NOT_CANCELABLE")
    record = manager.get_status(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    return _serialize_record(record)


@router.post("/jobs/{job_id}/retry", summary="Retry a failed or expired job")
def retry_job(job_id: str, manager: JobManager = Depends(get_manager)) -> dict[str, Any]:
    record = manager.retry(job_id)
    if record is None:
        raise HTTPException(status_code=409, detail="UNABLE_TO_RETRY")
    return {
        "job_id": record.job_id,
        "status": record.status.value,
        "submitted_at": record.submitted_at,
        "parent_job_id": record.parent_job_id,
    }


@router.get("/jobs", summary="List recent jobs")
def list_jobs(
    limit: int = Query(50, ge=1, le=500),
    manager: JobManager = Depends(get_manager),
) -> dict[str, Any]:
    latest = manager.list_jobs(limit)
    return {"jobs": latest}


def _build_options(payload: dict[str, Any]) -> JobOptions:
    image_policy = str(payload.get("image_policy", "extract"))
    if image_policy not in {"extract", "ignore"}:
        raise HTTPException(status_code=400, detail="INVALID_IMAGE_POLICY")
    output_mode = str(payload.get("output_mode", "md"))
    if output_mode not in {"md", "zip", "both"}:
        raise HTTPException(status_code=400, detail="INVALID_OUTPUT_MODE")
    size_limit = payload.get("size_limit_mb")
    timeout = payload.get("timeout_s")
    normalize_headings = payload.get("normalize_headings", True)
    dedupe = bool(payload.get("dedupe", False))
    return JobOptions(
        image_policy=image_policy,  # type: ignore[arg-type]
        size_limit_mb=int(size_limit) if size_limit is not None else None,
        timeout_s=int(timeout) if timeout is not None else None,
        normalize_headings=bool(normalize_headings),
        output_mode=output_mode,  # type: ignore[arg-type]
        dedupe=dedupe,
    )


def _serialize_record(record: JobRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": record.job_id,
        "status": record.status.value,
        "progress": record.progress,
        "submitted_at": record.submitted_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "warnings": record.warnings,
        "error_code": record.error_code,
        "error_message": record.error_message,
        "reused": record.reused,
        "parent_job_id": record.parent_job_id,
    }
    payload["artifacts"] = asdict(record.artifacts) if record.artifacts else None
    return payload


__all__ = ["router", "get_manager", "get_config"]

