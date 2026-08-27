from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.2.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_data_dir: Path = Field(default=Path("./data"), validation_alias="APP_DATA_DIR")
    database_url: str = Field(
        default="sqlite:///./data/app.db",
        validation_alias="DATABASE_URL",
    )
    agent_adapter: str = Field(default="stagehand", validation_alias="AGENT_ADAPTER")
    openclaw_cmd: str | None = Field(default="openclaw", validation_alias="OPENCLAW_CMD")
    openclaw_base_url: str | None = Field(default=None, validation_alias="OPENCLAW_BASE_URL")
    openclaw_timeout_sec: int = Field(default=600, validation_alias="OPENCLAW_TIMEOUT_SEC")
    chrome_devtools_url: str = Field(
        default="http://127.0.0.1:9222",
        validation_alias="CHROME_DEVTOOLS_URL",
    )
    stagehand_mode: str = Field(default="python", validation_alias="STAGEHAND_MODE")

    @property
    def data_dir(self) -> Path:
        return self.app_data_dir.resolve()


settings = Settings()
