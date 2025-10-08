# Local File-to-Markdown Conversion Toolkit

This project provides an offline-first workflow for converting common document formats into
normalized Markdown. It exposes both a command line interface (CLI) and an optional FastAPI
application, writing all artifacts to a structured `./runs/` directory so outputs never leave the
local machine.

## Features

- Supported inputs: `docx`, `pptx`, `xlsx`, `pdf`, `html`, `txt`, `eml`.
- Deterministic Markdown generation with consistent heading, list, and link formatting.
- Asset extraction to per-run folders with relative Markdown references.
- Strict MIME + extension validation, size guards, and timeout enforcement.
- JSONL run logs plus batch summaries written to `runs/summary.csv`.
- Optional FastAPI service (`POST /convert`, `POST /batch`) gated by configuration.
- Utilities for batch processing, run cleanup, and deterministic run identifiers.

## Project Layout

```
├── config.toml            # Default runtime configuration
├── docs/
│   └── WBS.md             # Detailed work breakdown structure and acceptance criteria
├── src/
│   ├── api/
│   │   ├── app.py         # FastAPI factory using dependency injection
│   │   └── routers/       # Route modules (conversion + health)
│   ├── core/
│   │   ├── constraint/    # Fixed runtime constraints and defaults
│   │   ├── markdown_converter/
│   │   │   ├── adapters/  # Format-specific adapters
│   │   │   ├── cli/       # Typer-powered CLI definitions
│   │   │   ├── config.py  # Configuration loader and models
│   │   │   ├── core.py    # Conversion service orchestration
│   │   │   ├── detection.py
│   │   │   ├── logging.py
│   │   │   └── utils.py
│   │   └── settings.py    # Environment-derived runtime settings
│   └── main.py            # CLI entrypoint
└── tests/                 # Pytest suite (unit + smoke tests)
```

## Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) or `pip` for dependency management

The project ships with a `pyproject.toml` so you can install dependencies via `uv`, `pip`, or any
PEP 517 compatible tool.

```bash
uv sync  # or: pip install -e .
```

To install development extras (tests, linting, type-checking):

```bash
uv sync --group dev --group test
```

## CLI Usage

The CLI is available via `python -m core.markdown_converter.cli` or the repository entrypoint
`python src/main.py`. Examples assume you are in the project root.

### Single File Conversion

```bash
python src/main.py convert ./fixtures/sample.docx
```

Output:

- Markdown: `./runs/<run_id>/output.md`
- Assets: `./runs/<run_id>/assets/`
- Log: `./runs/<run_id>/log.jsonl`

The CLI prints the destination paths and exits with status `0` on success. Failures report a
machine-readable error code (e.g., `UNSUPPORTED_MIME`, `SIZE_LIMIT`, `TIMEOUT`).

### Batch Conversion

```bash
python src/main.py batch ./incoming --parallel 4
```

- Processes all files under `./incoming` sequentially or in parallel (configurable).
- Each file receives its own run directory unless `--single-run` is provided.
- Batch statistics append to `runs/summary.csv`.

### Cleanup

```bash
python src/main.py clean --older-than 30
python src/main.py clean --keep 20
```

Removes stale run directories by age or count to reclaim disk space.

## Configuration

Runtime behavior is controlled via `config.toml`. Key options include:

- `runtime.output_dir`: Destination for run folders (`runs` by default).
- `runtime.max_file_size_mb`: Hard cap for input files.
- `runtime.convert_timeout_s`: Maximum conversion time per file.
- `runtime.parallelism`: Default CLI parallelism.
- `runtime.enable_local_api`: Toggle for FastAPI routes.
- `formats.allowed`: MIME allow list enforced during detection.

See [CONFIG.md](CONFIG.md) for a full reference and defaults.

## Local API (Optional)

To enable the API, set `enable_local_api = true` under `[runtime]` in `config.toml` and launch:

```bash
uvicorn api.app:create_app --factory --reload
```

Endpoints:

- `POST /convert`: Accepts `multipart/form-data` upload with a single `file` field.
- `POST /batch`: Accepts multiple `file` fields; returns run metadata and batch summary.

Responses include the `run_id`, absolute paths to `output.md` and the `assets` directory, plus any
warnings. Size and MIME policies mirror the CLI.

## Testing & Quality Gates

```bash
uv run pytest
uv run ruff check
uv run mypy
```

The `tests/` suite covers detection logic, filesystem hygiene, and smoke tests for the conversion
service. Ruff and mypy ensure code style and typing discipline.

## Known Limitations

- OCR for image-heavy PDFs is out of scope for this phase; see [KNOWN_ISSUES.md](KNOWN_ISSUES.md).
- Complex Excel workbooks may require manual post-processing for optimal readability.
- FastAPI server is intentionally local-only; no remote deployment components are included.

## License

This project is provided without a specific license. Adapt as needed for local use.
