"""Application configuration using pydantic-settings."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # OpenAlex API
    openalex_api_key: str

    # Rate limiting
    openalex_rate_limit: int = 100  # requests per second

    # Caching
    cache_ttl_days: int = 7

    # Defaults for project config
    default_max_iterations: int = 5
    default_max_papers: int = 500
    default_papers_per_iteration: int = 50
    default_growth_threshold: float = 0.05
    default_novelty_threshold: float = 0.10


def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()


# Project directory constants
SNOWBALL_DIR_NAME = ".snowball"
CONFIG_FILE_NAME = "config.json"
DATABASE_FILE_NAME = "snowball.db"
CACHE_DIR_NAME = "cache"
DOWNLOADS_DIR_NAME = "downloads"


def get_project_dir(base_path: Path | None = None) -> Path:
    """Get the .snowball directory path."""
    base = base_path or Path.cwd()
    return base / SNOWBALL_DIR_NAME


def ensure_project_dirs(base_path: Path | None = None) -> Path:
    """Create project directories if they don't exist."""
    project_dir = get_project_dir(base_path)
    project_dir.mkdir(exist_ok=True)
    (project_dir / CACHE_DIR_NAME).mkdir(exist_ok=True)
    (project_dir / DOWNLOADS_DIR_NAME).mkdir(exist_ok=True)
    return project_dir
