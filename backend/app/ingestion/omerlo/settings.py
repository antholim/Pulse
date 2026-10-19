from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class OmerloSettings(BaseSettings):
    """Connection settings for the Omerlo Reader API, read from OMERLO_* variables."""

    model_config = SettingsConfigDict(env_prefix="OMERLO_", extra="ignore")

    base_url: HttpUrl
    token_url: HttpUrl
    client_id: str
    client_secret: SecretStr
    media_id: str
    timeout_seconds: float = 30.0
    # Refresh the token this many seconds before it expires.
    token_refresh_margin_seconds: int = 60
