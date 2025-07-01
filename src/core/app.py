from fastapi import FastAPI

def create_app() -> FastAPI:
    """
    Creates and configures a FastAPI application instance.

    Returns:
        FastAPI: The configured FastAPI application.
    """
    app = FastAPI()

    # Add configuration, middleware, and routers here
    # Example:
    # from app.api.routes import health
    # app.include_router(health.router, prefix="/health", tags=["health"])

    return app

if __name__ == "__main__":
    # Example usage (for development)
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)