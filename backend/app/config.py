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
    # Dev-only overrides — leave unset in production. ANTHROPIC_MODEL swaps in a
    # cheaper model (e.g. claude-haiku-5-5); ANTHROPIC_BASE_URL points the client
    # at an Anthropic-compatible local server such as Ollama
    # (http://localhost:11434, with any placeholder ANTHROPIC_API_KEY).
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_base_url: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
