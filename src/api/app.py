from __future__ import annotations

from fastapi import FastAPI

from core.markdown_converter.config import AppConfig, load_config
from core.markdown_converter.core import ConversionService
from core.settings import Settings, get_settings

from .routers import convert, health


def create_app() -> FastAPI:
    settings = get_settings()
    config = _prepare_config(settings)
    if not config.runtime.enable_local_api:
        raise RuntimeError("Local API is disabled. Enable it via configuration or environment.")

    app = FastAPI(title="Local Markdown Converter", version="0.1.0")
    app.state.config = config
    app.state.service = ConversionService(config)

    app.include_router(health.router)
    app.include_router(convert.router)

    return app


def _prepare_config(settings: Settings) -> AppConfig:
    config = load_config(settings.config_path)
    if settings.enable_local_api is not None:
        config.runtime.enable_local_api = settings.enable_local_api
    return config


__all__ = ["create_app"]
