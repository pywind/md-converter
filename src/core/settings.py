from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .constraint import DEFAULT_CONFIG_PATH, ENV_PREFIX


@dataclass(frozen=True, slots=True)
class Settings:
    """Application runtime settings sourced from environment variables."""

    config_path: Path = DEFAULT_CONFIG_PATH
    enable_local_api: bool | None = None


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _read_settings() -> Settings:
    config_env = os.getenv(f"{ENV_PREFIX}CONFIG_PATH")
    enable_env = os.getenv(f"{ENV_PREFIX}ENABLE_LOCAL_API")
    config_path = Path(config_env) if config_env else DEFAULT_CONFIG_PATH
    enable_local_api = _parse_bool(enable_env)
    return Settings(config_path=config_path, enable_local_api=enable_local_api)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return _read_settings()


__all__ = ["Settings", "get_settings"]
