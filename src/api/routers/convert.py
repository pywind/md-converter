from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.dependencies import get_config, get_service
from api.utils import run_sync
from core.markdown_converter.config import AppConfig
from core.markdown_converter.core import ConversionError, ConversionService

router = APIRouter(tags=["conversion"])


@router.post("/convert", summary="Convert a single document")
async def convert_document(
    file: UploadFile = File(...),
    service: ConversionService = Depends(get_service),
    config: AppConfig = Depends(get_config),
) -> dict[str, str | list[str]]:
    suffix = Path(file.filename or "upload").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        _enforce_size_limit(content, config)
        tmp.write(content)
        tmp.flush()
        tmp_path = Path(tmp.name)
    try:
        result = await run_sync(service.convert_file, tmp_path)
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


@router.post("/batch", summary="Convert multiple documents")
async def batch_convert(
    files: List[UploadFile] = File(...),
    service: ConversionService = Depends(get_service),
    config: AppConfig = Depends(get_config),
) -> dict[str, list[dict[str, str | list[str]]] | dict[str, object]]:
    temp_files: list[Path] = []
    results: list[dict[str, str | list[str]]] = []
    try:
        for upload in files:
            suffix = Path(upload.filename or "upload").suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                content = await upload.read()
                _enforce_size_limit(content, config)
                tmp.write(content)
                tmp.flush()
                temp_files.append(Path(tmp.name))
        batch_result = await run_sync(service.batch_convert, temp_files)
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
        summary_dict: dict[str, object] = {
            "total": summary.total,
            "successes": summary.successes,
            "failures": summary.failures,
            "warnings": summary.warnings,
        }
    finally:
        for path in temp_files:
            path.unlink(missing_ok=True)
    return {"results": results, "summary": summary_dict}


def _enforce_size_limit(payload: bytes, config: AppConfig) -> None:
    max_bytes = config.runtime.max_file_size_mb * 1024 * 1024
    if len(payload) > max_bytes:
        raise HTTPException(status_code=413, detail="SIZE_LIMIT")


__all__ = [
    "router",
]
