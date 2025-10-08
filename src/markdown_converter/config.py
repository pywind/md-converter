from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping


CONFIG_FILE = Path("config.toml")


@dataclass(slots=True)
class LimitConfig:
    max_pages: int = 500
    max_slides: int = 500
    max_sheets: int = 50


@dataclass(slots=True)
class BatchConfig:
    default_parallelism: int = 1
    single_run_default: bool = False


@dataclass(slots=True)
class RuntimeConfig:
    output_dir: Path = Path("runs")
    log_file: str = "log.jsonl"
    summary_csv: str = "summary.csv"
    max_file_size_mb: int = 25
    convert_timeout_s: int = 100
    enable_local_api: bool = False
    parallelism: int = 1
    limits: LimitConfig = field(default_factory=LimitConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)


@dataclass(slots=True)
class APIConfig:
    host: str = "127.0.0.1"
    port: int = 8000


@dataclass(slots=True)
class AppConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    formats: tuple[str, ...] = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/pdf",
        "text/html",
        "text/plain",
        "message/rfc822",
    )
    api: APIConfig = field(default_factory=APIConfig)

    @property
    def allowed_mime_types(self) -> tuple[str, ...]:
        return self.formats


def _read_toml(path: Path) -> Mapping[str, object]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _build_limits(data: Mapping[str, object] | None) -> LimitConfig:
    if not data:
        return LimitConfig()
    return LimitConfig(
        max_pages=int(data.get("max_pages", 500)),
        max_slides=int(data.get("max_slides", 500)),
        max_sheets=int(data.get("max_sheets", 50)),
    )


def _build_batch(data: Mapping[str, object] | None) -> BatchConfig:
    if not data:
        return BatchConfig()
    return BatchConfig(
        default_parallelism=int(data.get("default_parallelism", 1)),
        single_run_default=bool(data.get("single_run_default", False)),
    )


def _build_runtime(data: Mapping[str, object] | None) -> RuntimeConfig:
    if not data:
        return RuntimeConfig()
    limits = _build_limits(data.get("limits") if isinstance(data, Mapping) else None)
    batch = _build_batch(data.get("batch") if isinstance(data, Mapping) else None)
    return RuntimeConfig(
        output_dir=Path(str(data.get("output_dir", "runs"))),
        log_file=str(data.get("log_file", "log.jsonl")),
        summary_csv=str(data.get("summary_csv", "summary.csv")),
        max_file_size_mb=int(data.get("max_file_size_mb", 25)),
        convert_timeout_s=int(data.get("convert_timeout_s", 100)),
        enable_local_api=bool(data.get("enable_local_api", False)),
        parallelism=int(data.get("parallelism", 1)),
        limits=limits,
        batch=batch,
    )


def _build_api(data: Mapping[str, object] | None) -> APIConfig:
    if not data:
        return APIConfig()
    return APIConfig(host=str(data.get("host", "127.0.0.1")), port=int(data.get("port", 8000)))


def _tuple_of_strings(value: object | None, default: Iterable[str]) -> tuple[str, ...]:
    if not value:
        return tuple(default)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    raise TypeError(f"Unsupported formats configuration: {value!r}")


def load_config(path: Path | None = None) -> AppConfig:
    path = path or CONFIG_FILE
    raw = _read_toml(path)
    runtime_data = raw.get("runtime") if isinstance(raw, Mapping) else None
    formats_data = raw.get("formats") if isinstance(raw, Mapping) else None
    api_data = raw.get("api") if isinstance(raw, Mapping) else None
    runtime = _build_runtime(runtime_data if isinstance(runtime_data, Mapping) else None)
    formats = _tuple_of_strings(formats_data if isinstance(formats_data, Iterable) else None, AppConfig().formats)
    api = _build_api(api_data if isinstance(api_data, Mapping) else None)
    return AppConfig(runtime=runtime, formats=formats, api=api)


def dump_config(config: AppConfig) -> str:
    payload = {
        "runtime": {
            "output_dir": str(config.runtime.output_dir),
            "log_file": config.runtime.log_file,
            "summary_csv": config.runtime.summary_csv,
            "max_file_size_mb": config.runtime.max_file_size_mb,
            "convert_timeout_s": config.runtime.convert_timeout_s,
            "enable_local_api": config.runtime.enable_local_api,
            "parallelism": config.runtime.parallelism,
            "limits": {
                "max_pages": config.runtime.limits.max_pages,
                "max_slides": config.runtime.limits.max_slides,
                "max_sheets": config.runtime.limits.max_sheets,
            },
            "batch": {
                "default_parallelism": config.runtime.batch.default_parallelism,
                "single_run_default": config.runtime.batch.single_run_default,
            },
        },
        "formats": list(config.allowed_mime_types),
        "api": {
            "host": config.api.host,
            "port": config.api.port,
        },
    }
    return json.dumps(payload, indent=2)
