from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HYDROPULSE_", env_file=".env")

    database_url: str = "sqlite:///./data/hydropulse.db"
    data_dir: Path = Path("data")
    artifact_dir: Path = Path("artifacts")
    operator_token: str = Field(default="local-development-token", min_length=12)
    ingestion_mode: str = "direct"
    observation_retention_days: int = 90
    max_history_days: int = 31
    project_disk_budget_gb: int = 35


@lru_cache
def get_settings() -> Settings:
    return Settings()
