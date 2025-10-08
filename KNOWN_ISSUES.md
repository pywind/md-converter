# Known Issues & Limitations

The current release focuses on deterministic, offline Markdown conversion. The following scenarios
may require manual intervention or future enhancements.

## Scanned or Image-Heavy PDFs

- **Symptom:** Output Markdown contains little to no text with `IMAGE_HEAVY_PDF` warnings.
- **Mitigation:** Enable OCR in downstream tooling or request original text-based PDFs. OCR support is
  planned for a future phase.

## Complex Excel Workbooks

- **Symptom:** Wide or deeply nested tables flatten into long Markdown rows flagged with
  `TABLES_FLATTENED` warnings.
- **Mitigation:** Split large sheets prior to conversion or export to CSV for manual curation.

## Email Attachments

- **Symptom:** Binary attachments from `.eml` files are saved to assets but not rendered inline.
- **Mitigation:** Inspect the asset folder and open attachments with appropriate local viewers.

## Large Slide Decks

- **Symptom:** Numerous slide images increase run directory size.
- **Mitigation:** Review slide decks before conversion and remove redundant media. Future work may add
  configurable caps for image extraction.

## Missing Dependencies

- **Symptom:** Errors referencing the `markitdown` package when converting Office/PDF/HTML content.
- **Mitigation:** Install project dependencies via `uv sync` or `pip install -e .` to ensure
  `markitdown` is available.

If you encounter additional limitations, document them here to guide roadmap decisions.
