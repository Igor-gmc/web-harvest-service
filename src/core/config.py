from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="bankruptcy_parser")
    app_env: str = Field(default="dev")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/bankruptcy_parser"
    )

    input_xlsx_path: str = Field(default="input/identifiers.xlsx")
    proxies_file: str = Field(default="input/proxies.txt")

    use_proxies: bool = Field(default=False)
    enable_direct_worker: bool = Field(default=True)

    playwright_headless: bool = Field(default=True)
    browser_timeout_ms: int = Field(default=30000)

    max_concurrent_workers: int = Field(default=1)
    max_tasks_per_proxy: int = Field(default=1)

    request_delay_min: int = Field(default=1)
    request_delay_max: int = Field(default=3)

    retry_attempts: int = Field(default=3)
    retry_base_delay: int = Field(default=2)

    lock_ttl_seconds: int = Field(default=60)
    heartbeat_interval_seconds: int = Field(default=15)


settings = Settings()
