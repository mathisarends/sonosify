from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _CloudSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        env_prefix="SONOSIFY_CLOUD_",
        extra="ignore",
    )

    client_id: str | None = None
    client_secret: SecretStr | None = None
    redirect_uri: str | None = None
    access_token: SecretStr | None = None
    app_id: str | None = None
    household_id: str | None = None
    token_cache: Path | None = None
