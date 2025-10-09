"""FastAPI dependency providers for application services."""

from __future__ import annotations

from fastapi import HTTPException, Request

from core.markdown_converter.config import AppConfig
from core.markdown_converter.core import ConversionService
from core.markdown_converter.jobs import JobManager


def get_config(request: Request) -> AppConfig:
    config = getattr(request.app.state, "config", None)
    if config is None:
        raise HTTPException(status_code=503, detail="CONFIG_UNAVAILABLE")
    return config


def get_service(request: Request) -> ConversionService:
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="SERVICE_UNAVAILABLE")
    return service


def get_job_manager(request: Request) -> JobManager:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="MANAGER_UNAVAILABLE")
    return manager


__all__ = ["get_config", "get_service", "get_job_manager"]
