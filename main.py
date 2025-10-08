from fastapi import FastAPI, HTTPException

from api import create_app

try:
    app = create_app()
except RuntimeError:
    app = FastAPI(title="Local Markdown Converter", version="0.1.0")

    @app.get("/")
    async def api_disabled() -> dict[str, str]:
        raise HTTPException(
            status_code=503,
            detail="Local API disabled. Enable by setting enable_local_api = true in config.toml",
        )
