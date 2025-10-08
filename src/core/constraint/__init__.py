from __future__ import annotations

from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config.toml")
ENV_PREFIX = "LMC_"

__all__ = ["DEFAULT_CONFIG_PATH", "ENV_PREFIX"]
