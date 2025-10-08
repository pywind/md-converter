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
- Optional FastAPI job service that queues work asynchronously and exposes polling endpoints.
- Utilities for batch processing, run cleanup, and deterministic run identifiers.

## Project Layout

```
├── config.toml            # Default runtime configuration
├── docs/
│   └── WBS.md             # Detailed work breakdown structure and acceptance criteria
├── src/
│   ├── api/
│   │   ├── app.py         # FastAPI factory using dependency injection
│   │   └── routers/       # Route modules (jobs + health)
│   ├── core/
│   │   ├── constraint/    # Fixed runtime constraints and defaults
│   │   ├── markdown_converter/
│   │   │   ├── adapters/  # Format-specific adapters
│   │   │   ├── cli/       # Typer-powered CLI definitions
│   │   │   ├── config.py  # Configuration loader and models
│   │   │   ├── core.py    # Conversion service orchestration
│   │   │   ├── jobs.py    # Asynchronous job management and persistence
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
- `runtime.jobs.*`: Worker pool sizing, dedupe behavior, and retention policies for the job queue.
- `formats.allowed`: MIME allow list enforced during detection.

See [CONFIG.md](CONFIG.md) for a full reference and defaults.

## Local API (Optional)

To enable the API, set `enable_local_api = true` under `[runtime]` in `config.toml` and launch:

```bash
uvicorn api.app:create_app --factory --reload
```

### Asynchronous job API

The API is intentionally non-blocking: submissions return immediately with a job identifier while a
background worker pool performs the conversion. All responses reference absolute local paths under
`./runs/` so callers can integrate with downstream tooling without streaming file contents.

**Submission**

- `POST /api/v1/jobs`
  - form-data: `file` (required), optional `options` JSON string
    - `image_policy`: `"extract"|"ignore"`
    - `size_limit_mb`: integer override (`<=` config cap)
    - `timeout_s`: per-job timeout (`<=` config cap)
    - `normalize_headings`: boolean
    - `output_mode`: `"md"|"zip"|"both"`
    - `dedupe`: boolean (enable artifact reuse when the same content+options are seen)
  - response: `{ job_id, status: "queued", submitted_at, progress }`

**Status & lifecycle**

- `GET /api/v1/jobs/{job_id}` returns the canonical job record including
  `{ status, progress, submitted_at, started_at?, finished_at?, warnings, error_code?,
  error_message?, parent_job_id?, reused?, artifacts? }`.
- `GET /api/v1/jobs` lists the most recent N job records from the append-only index.

Jobs transition through the following state machine:

```
queued → running → succeeded
                   ↘
                    failed ↘
                             canceled → expired (retention sweep)
```

Progress updates follow deterministic milestones: `0.1` read/validate, `0.2` detect MIME,
`0.6` convert, `0.8` asset write, `1.0` finalize (zip + summary). Cancel requests flip queued jobs
immediately and signal running workers, which respect the cancellation flag before finalization.

**Result metadata**

- `GET /api/v1/jobs/{job_id}/result`
  - only available for `succeeded` or `expired` jobs.
  - returns `{ artifacts: { output_md_path, assets_dir_path, run_dir_path, output_zip_path?,
    size_bytes_md, size_bytes_assets_total }, reused }`.
  - `?as=zip` adds `zip_path` pointing at `./runs/{job_id}/output.zip` (created when
    `output_mode` is `zip` or `both`).

**Control operations**

- `POST /api/v1/jobs/{job_id}/cancel` best-effort cancellation; returns the updated status.
- `POST /api/v1/jobs/{job_id}/retry` resubmits failed/canceled/expired jobs with their cached input,
  linking lineage via `parent_job_id`.

**Durability & retention**

- Per-job `status.json` is the source of truth; logs and summaries reside under each run directory.
- `runs/_index/jobs.jsonl` and `runs/_index/latest.json` track history for quick listing.
- A background retention thread marks terminal jobs older than `runtime.jobs.retention_days` as
  `expired`, archives their status, and removes artifacts. Queries to `/jobs/{job_id}` continue to
  return the archived metadata.

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
