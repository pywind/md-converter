from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "My FastAPI App"
    admin_email: str = "admin@example.com"
    items_per_user: int = 100

    class Config:
        env_file = ".env"