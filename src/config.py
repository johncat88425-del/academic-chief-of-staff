"""Application configuration via environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global settings loaded from .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Google Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"

    # Microsoft Graph (Outlook)
    azure_client_id: str = ""
    azure_tenant_id: str = ""
    azure_client_secret: str = ""
    azure_redirect_uri: str = "http://localhost:8400/callback"

    # Storage paths
    db_path: Path = Path("./data/state.db")
    chroma_path: Path = Path("./data/chroma")
    syllabus_dir: Path = Path("./syllabi")

    # Scheduling defaults
    starter_pack_lead_days: int = 7  # T-minus days before due date
    deep_work_block_minutes: int = 90
    crunch_week_threshold: float = 0.3  # total weight threshold to trigger alert


settings = Settings()
