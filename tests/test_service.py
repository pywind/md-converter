from pathlib import Path

from markdown_converter.config import AppConfig, BatchConfig, LimitConfig, RuntimeConfig
from markdown_converter.core import ConversionService


def build_config(output_dir: Path) -> AppConfig:
    runtime = RuntimeConfig()
    runtime.output_dir = output_dir
    runtime.log_file = "log.jsonl"
    runtime.summary_csv = "summary.csv"
    runtime.batch = BatchConfig()
    runtime.limits = LimitConfig()
    return AppConfig(runtime=runtime)


def test_convert_txt_creates_run(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("hello world", encoding="utf-8")
    config = build_config(tmp_path / "runs")
    service = ConversionService(config)
    result = service.convert_file(source)
    assert result.output_path.exists()
    assert result.output_path.read_text(encoding="utf-8").strip() == "hello world"
    assert result.assets_dir.exists()


def test_batch_single_run(tmp_path: Path) -> None:
    file_a = tmp_path / "a.txt"
    file_a.write_text("A", encoding="utf-8")
    file_b = tmp_path / "b.txt"
    file_b.write_text("B", encoding="utf-8")
    config = build_config(tmp_path / "runs")
    service = ConversionService(config)
    result = service.batch_convert([file_a, file_b], single_run=True)
    assert result.summary.total == 2
    assert result.summary.successes == 2
    assert result.runs[0].output_path.exists()
