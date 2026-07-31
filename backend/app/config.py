from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    jwt_secret: str = "dev-secret-change-in-production"
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"

    environment: str = "development"  # set to "production" in Cloud Run

    # Todo assistant (Phase B). Empty string disables the /api/chat routes with
    # a clear 503 rather than a confusing downstream auth error.
    anthropic_api_key: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
