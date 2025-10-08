# Configuration Reference

The service reads settings from `config.toml` in the project root. All values are optional—missing
keys fall back to the defaults shown below.

```toml
[runtime]
output_dir = "runs"
log_file = "log.jsonl"
summary_csv = "summary.csv"
max_file_size_mb = 25
convert_timeout_s = 100
enable_local_api = false
parallelism = 1

[runtime.limits]
max_pages = 500
max_slides = 500
max_sheets = 50

[runtime.batch]
default_parallelism = 1
single_run_default = false

[formats]
allowed = [
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/pdf",
  "text/html",
  "text/plain",
  "message/rfc822",
]

[api]
host = "127.0.0.1"
port = 8000
```

## Settings

### `[runtime]`

- **`output_dir`** — Root directory for run artifacts. Each conversion writes to `runs/<run_id>/`.
- **`log_file`** — File name for JSONL run logs stored in each run directory.
- **`summary_csv`** — Batch summary file relative to `output_dir`.
- **`max_file_size_mb`** — Reject inputs larger than this threshold.
- **`convert_timeout_s`** — Hard limit for per-file conversion. Timeouts raise a `TIMEOUT` error.
- **`enable_local_api`** — Enable FastAPI routes when `true`. The CLI works regardless.
- **`parallelism`** — Default worker count for CLI batch jobs (overridable via `--parallel`).

### `[runtime.limits]`

Sanity guards for adapter-specific processing. Currently informational; tune as needed.

### `[runtime.batch]`

- **`default_parallelism`** — Worker count when `--parallel` is omitted.
- **`single_run_default`** — Whether batch invocations combine all inputs into a single Markdown file.

### `[formats]`

List of MIME types accepted by the detection layer. Both the extension and MIME sniff must match an
entry here or conversion fails with `UNSUPPORTED_MIME`.

### `[api]`

- **`host`**, **`port`** — Bind settings used when launching `uvicorn` with the factory
  `markdown_converter.api:create_app`.

## Tips

- Set `output_dir` to a dedicated disk with ample space for large batches.
- For long-running batches, consider bumping `parallelism` while monitoring CPU/RAM headroom.
- When experimenting, copy `config.toml` to `config.local.toml` and pass `--config` to CLI commands to
  avoid modifying the default profile.
