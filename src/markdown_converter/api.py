from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile

from .config import load_config
from .core import ConversionError, ConversionService


def create_app(config_path: Path | None = None, *, require_enabled: bool = True) -> FastAPI:
    config = load_config(config_path)
    if require_enabled and not config.runtime.enable_local_api:
        raise RuntimeError("Local API is disabled. Enable it via config.runtime.enable_local_api")
    service = ConversionService(config)
    app = FastAPI(title="Local Markdown Converter", version="0.1.0")

    @app.post("/convert")
    async def convert(file: UploadFile = File(...)) -> dict[str, str | list[str]]:
        suffix = Path(file.filename or "upload").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            max_bytes = config.runtime.max_file_size_mb * 1024 * 1024
            if len(content) > max_bytes:
                raise HTTPException(status_code=413, detail="SIZE_LIMIT")
            tmp.write(content)
            tmp.flush()
            tmp_path = Path(tmp.name)
        try:
            result = service.convert_file(tmp_path)
        except ConversionError as exc:
            raise HTTPException(status_code=400, detail=exc.code) from exc
        finally:
            tmp_path.unlink(missing_ok=True)
        return {
            "run_id": result.run_id,
            "output_path": str(result.output_path.resolve()),
            "assets_path": str(result.assets_dir.resolve()),
            "warnings": result.warnings,
        }

    @app.post("/batch")
    async def batch(files: List[UploadFile] = File(...)) -> dict[str, list[dict[str, str | list[str]]]]:
        temp_files: list[Path] = []
        results: list[dict[str, str | list[str]]] = []
        summary_dict = {"total": 0, "successes": 0, "failures": 0, "warnings": {}}
        try:
            for upload in files:
                suffix = Path(upload.filename or "upload").suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    content = await upload.read()
                    max_bytes = config.runtime.max_file_size_mb * 1024 * 1024
                    if len(content) > max_bytes:
                        raise HTTPException(status_code=413, detail="SIZE_LIMIT")
                    tmp.write(content)
                    tmp.flush()
                    path = Path(tmp.name)
                    temp_files.append(path)
            batch_result = service.batch_convert(temp_files)
            for item in batch_result.runs:
                results.append(
                    {
                        "run_id": item.run_id,
                        "output_path": str(item.output_path.resolve()),
                        "assets_path": str(item.assets_dir.resolve()),
                        "warnings": item.warnings,
                    }
                )
            summary = batch_result.summary
            summary_dict = {
                "total": summary.total,
                "successes": summary.successes,
                "failures": summary.failures,
                "warnings": summary.warnings,
            }
        finally:
            for path in temp_files:
                path.unlink(missing_ok=True)
        return {"results": results, "summary": summary_dict}

    return app
