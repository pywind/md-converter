# Local File-to-Markdown Conversion Service — Work Breakdown Structure

## Overview

This document captures the scope, milestones, and acceptance criteria for delivering a purely local, single-machine service that converts supported files to Markdown using the `markitdown` library. The service must operate entirely offline, storing outputs under a structured `./runs/` directory and offering both CLI and optional localhost API interfaces.

## Goals and Non-Goals

- **Primary goals**
  - Convert `docx`, `pptx`, `xlsx`, `pdf`, `html`, `txt`, and `eml` files to normalized Markdown, extracting local assets per run.
  - Provide CLI tooling and a toggleable FastAPI endpoint for local use only.
  - Enforce deterministic behavior, resource limits, and comprehensive logging/observability.
- **Deferred / Non-goals**
  - Cloud or container deployment, background workers, authentication, or remote storage.
  - OCR/image-to-text processing and complex parallel image pipelines.
  - GUI clients (future phase once API exists).

## Epic-Level Breakdown

### Epic A — Project Setup (Local)

1. **A1. Repository scaffold**
   - Initialize dependency management (`uv` or `poetry`).
   - Configure linting (ruff), type checking (mypy), testing (pytest), and pre-commit hooks.
2. **A2. Configuration management**
   - Author `config.toml` defining allowed MIME types, size/time limits, output paths, and optional feature toggles.
3. **A3. Logging foundation**
   - Emit JSON Lines logs to `./runs/{run_id}/log.jsonl`.
   - Produce human-readable run summaries for CLI output.

### Epic B — Document Adapters & Core Conversion

1. **B1. Markitdown integration**
   - Add dependency and confirm MIME-to-adapter mapping.
2. **B2. CoreFacade orchestration**
   - Detect MIME and extension, fail on mismatch.
   - Route to appropriate adapter and aggregate metadata, warnings, and assets.
   - Apply Markdown normalization (headings, links, newline policy).
3. **B3. Format-specific adapters**
   - **DOCXAdapter**: preserve paragraphs, headings, lists, and export embedded images.
   - **PPTXAdapter**: map slide titles to `##`, append speaker notes, export slide assets.
   - **XLSXAdapter**: render sheets as sections; flatten tables to readable Markdown blocks.
   - **PDFAdapter**: prioritize text extraction; flag image-heavy content.
   - **HTMLAdapter**: remove scripts/styles, keep links and anchors.
   - **TXTAdapter**: passthrough with minimal cleanup.
   - **EMLAdapter**: subject as `#` heading; body content to Markdown; attachments saved under assets.
4. **B4. Output specification**
   - Write Markdown to `./runs/{run_id}/output.md` and assets to `./runs/{run_id}/assets/` with relative links (`./assets/<name>`).
5. **B5. Resource guards**
   - Enforce file size, page/slide/sheet limits, and per-file timeouts.

### Epic D — Optional Local API (localhost only)

1. **D1. FastAPI service**
   - Endpoints: `POST /convert` and `POST /batch`.
   - Disabled by default via configuration.
2. **D2. Upload validation**
   - Enforce MIME allow-list and configured size caps.
3. **D3. Run directory integration**
   - API writes through the same `./runs/{run_id}` structure.
   - Responses return `run_id`, absolute path to `output.md`, and assets directory.
4. **D4. Configuration toggle**
   - Respect `enable_local_api` flag in configuration.

### Epic E — Storage & File Hygiene

1. **E1. Run directory lifecycle**
   - Generate timestamped, collision-safe `run_id` folders.
2. **E2. Safe filename handling**
   - Slugify filenames, enforce ASCII, and cap length to prevent path traversal.
3. **E3. Cleanup utility**
   - CLI command `clean --older-than DAYS` or `clean --keep N`.

### Epic F — Validation & Error Handling

1. **F1. Strict MIME + extension agreement**
   - Abort with `UNSUPPORTED_MIME` when mismatch occurs.
2. **F2. Error taxonomy**
   - Emit machine-readable error codes (e.g., `SIZE_LIMIT`, `TIMEOUT`).
3. **F3. Warning taxonomy**
   - Standardize warnings such as `IMAGE_HEAVY_PDF`, `TABLES_FLATTENED`, `ATTACHMENT_SKIPPED`.

### Epic G — Observability (Local)

1. **G1. Timing metrics**
   - Capture durations for read, detect, convert, and write phases.
2. **G2. Counters**
   - Track success/failure totals and warning counts by type.
3. **G3. Summary reporting**
   - Print per-run summary and append batch metrics to `./runs/summary.csv`.

### Epic H — Testing & Quality Assurance

1. **H1. Unit tests** for adapters, link normalization, and asset path correctness.
2. **H2. Golden snapshot tests** using representative sample files.
3. **H3. Large-file tests** targeting 10 MB and 25 MB inputs for timeout and memory behavior.
4. **H4. Pathological input tests** for corrupt files, zip-bomb-like PDFs, and oversized tables.
5. **H5. Determinism regression tests** verifying byte-identical Markdown outputs.

### Epic I — Documentation (Local Usage)

1. **I1. README** updates covering installation, CLI commands, and usage examples.
2. **I2. CONFIG.md** documenting each configuration option, defaults, and suggested tuning.
3. **I3. KNOWN_ISSUES.md** describing limitations (e.g., scanned PDFs, complex Excel tables) with mitigation tips.

## Acceptance Criteria

The project is considered complete when the following acceptance criteria are satisfied:

1. **Single-file CLI conversion**
   - `convert <file>` creates `./runs/{run_id}/output.md` and assets folder when needed, exits with code 0, and prints the run path.
2. **Batch conversion**
   - `batch <folder|glob>` handles ≥100 files sequentially; optional `--parallel N` functions without race conditions.
   - Generates either per-file runs or a consolidated run (`--single-run`) and records results in `./runs/summary.csv`.
3. **Adapter correctness**
   - All supported formats convert without crashing on well-formed inputs, exporting images and using relative asset links.
4. **Normalization standards**
   - Headings map consistently to Markdown `#` levels; hyperlinks and lists are preserved; LF line endings with no trailing whitespace.
5. **Local API behavior (if enabled)**
   - `POST /convert` returns `run_id`, output path, and asset directory; enforces size/MIME caps and returns JSON errors.
6. **Performance constraints**
   - ≤10 MB files finish within 100 seconds; memory usage stays ≤2× input size for text-first formats and avoids OOM for ≤25 MB within timeout.
7. **Batch throughput**
   - 100 mixed files (≈3 MB each) complete within 15 minutes sequentially; `--parallel 4` reduces wall time by ~50% ±20%.
8. **Timeout and size enforcement**
   - Over-limit files fail fast with explicit errors; batch processing continues.
9. **Deterministic outputs**
   - Identical inputs/configurations yield byte-identical Markdown (excluding timestamped log lines).
10. **Corruption handling**
    - Corrupt or unsupported files surface stable error codes; partial outputs remain only when `--keep-partials` is set.
11. **Atomic writes**
    - Markdown and assets write via temp files and atomic moves to prevent partial results.
12. **Local-only guarantee**
    - No external network calls occur; all artifacts reside under `./runs/`.
13. **Path safety**
    - Sanitized filenames prevent directory traversal or unsafe paths.
14. **Run logging**
    - `log.jsonl` captures timing, size, warnings, and final status for each run.
15. **Batch summary**
    - CSV/JSON summaries report counts of successes, failures, and warnings by type.
16. **Documentation completeness**
    - README, CONFIG, and KNOWN_ISSUES cover installation, configuration, and known limitations.

## Risks & Mitigations

- **Scanned PDFs**: Text extraction may fail; emit `IMAGE_HEAVY_PDF` warnings and document future OCR toggle.
- **Complex XLSX tables**: Potential readability loss; document table flattening rules and consider optional CSV export in later phases.
- **Large slide decks**: High image volume; enforce image count/size caps, emit warnings, and continue processing.

## Future Considerations

- Phase 2 enhancements: OCR for image-based PDFs, image conversion, GUI clients consuming the local API, and optional CSV exports for Excel sheets.
- Telemetry and analytics remain local-only but can evolve to richer dashboards if needed.

