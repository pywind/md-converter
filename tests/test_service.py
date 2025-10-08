from __future__ import annotations

from pathlib import Path

from core.markdown_converter.config import AppConfig, BatchConfig, LimitConfig, RuntimeConfig
from core.markdown_converter.core import ConversionService


def build_config(tmp_path: Path) -> AppConfig:
    runtime = RuntimeConfig(output_dir=tmp_path, enable_local_api=True)
    runtime.limits = LimitConfig(max_pages=10, max_slides=10, max_sheets=5)
    runtime.batch = BatchConfig(default_parallelism=1, single_run_default=False)
    return AppConfig(runtime=runtime)


def test_conversion_service_handles_missing_file(tmp_path):
    service = ConversionService(build_config(tmp_path))
    try:
        service.convert_file(tmp_path / "missing.txt")
    except Exception as exc:  # noqa: BLE001
        assert str(exc)
    else:
        raise AssertionError("Exception expected")
