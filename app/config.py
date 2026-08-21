from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.6"


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
    agent_adapter: str = Field(default="browser-use", validation_alias="AGENT_ADAPTER")

    @property
    def data_dir(self) -> Path:
        return self.app_data_dir.resolve()


settings = Settings()
