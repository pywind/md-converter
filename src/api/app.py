from __future__ import annotations

from fastapi import FastAPI

from core.markdown_converter.config import AppConfig, load_config
from core.markdown_converter.core import ConversionService
from core.markdown_converter.jobs import JobManager
from core.settings import Settings, get_settings

from .routers import health, jobs


def create_app() -> FastAPI:
    settings = get_settings()
    config = _prepare_config(settings)
    if not config.runtime.enable_local_api:
        raise RuntimeError("Local API is disabled. Enable it via configuration or environment.")

    app = FastAPI(title="Local Markdown Converter", version="0.1.0")
    app.state.config = config
    service = ConversionService(config)
    app.state.service = service
    app.state.job_manager = JobManager(config, service)

    app.include_router(health.router)
    app.include_router(jobs.router)

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # pragma: no cover - FastAPI lifecycle
        manager: JobManager = app.state.job_manager
        manager.shutdown()

    return app


def _prepare_config(settings: Settings) -> AppConfig:
    config = load_config(settings.config_path)
    if settings.enable_local_api is not None:
        config.runtime.enable_local_api = settings.enable_local_api
    return config


__all__ = ["create_app"]
