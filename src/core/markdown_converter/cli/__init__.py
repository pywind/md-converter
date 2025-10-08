from __future__ import annotations

import shutil
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..config import AppConfig, load_config
from ..core import ConversionError, ConversionService
from ..utils import generate_run_id

console = Console()

app = typer.Typer(help="Local file-to-Markdown conversion toolkit")


def _load_config(path: Path | None) -> AppConfig:
    return load_config(path)


@app.command()
def convert(
    file: Path,
    config: Path | None = typer.Option(None, "--config", help="Path to config.toml"),
) -> None:
    cfg = _load_config(config)
    service = ConversionService(cfg)
    try:
        result = service.convert_file(file)
    except ConversionError as exc:
        console.print(f"[red]Conversion failed[/red]: {exc.code} - {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]Success[/green]: {result.summary}")
    console.print(f"Run assets: {result.assets_dir}")
    if result.zip_path:
        console.print(f"Output archive: {result.zip_path}")


@app.command()
def batch(
    path: list[Path],
    config: Path | None = typer.Option(None, "--config", help="Path to config.toml"),
    parallel: int | None = typer.Option(None, "--parallel", min=1, help="Parallel workers"),
    single_run: bool = typer.Option(False, "--single-run", help="Combine outputs into one run"),
) -> None:
    cfg = _load_config(config)
    service = ConversionService(cfg)
    batch_result = service.batch_convert(path, parallelism=parallel, single_run=single_run)
    table = Table(title="Batch summary")
    table.add_column("Run ID")
    table.add_column("Output")
    table.add_column("Warnings")
    for result in batch_result.runs:
        table.add_row(result.run_id, str(result.output_path), ", ".join(result.warnings) or "-")
    console.print(table)
    console.print(
        f"Processed {batch_result.summary.total} files — "
        f"{batch_result.summary.successes} succeeded, {batch_result.summary.failures} failed."
    )


@app.command()
def clean(
    older_than: int = typer.Option(
        0,
        "--older-than",
        min=0,
        help="Delete runs older than the given days",
    ),
    keep: int = typer.Option(
        0,
        "--keep",
        min=0,
        help="Keep the most recent N runs and delete the rest",
    ),
    config: Path | None = typer.Option(None, "--config", help="Path to config.toml"),
) -> None:
    cfg = _load_config(config)
    output_dir = cfg.runtime.output_dir
    if not output_dir.exists():
        console.print("No runs directory found.")
        raise typer.Exit()
    candidates = sorted([p for p in output_dir.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime)
    to_remove: list[Path] = []
    if keep:
        to_remove.extend(candidates[:-keep])
    if older_than:
        threshold = time.time() - older_than * 86400
        to_remove.extend([p for p in candidates if p.stat().st_mtime < threshold])
    seen: set[Path] = set()
    for path in to_remove:
        if path in seen:
            continue
        shutil.rmtree(path, ignore_errors=True)
        seen.add(path)
    console.print(f"Removed {len(seen)} run directories.")


@app.command()
def new_run_id() -> None:
    console.print(generate_run_id())


if __name__ == "__main__":
    app()
