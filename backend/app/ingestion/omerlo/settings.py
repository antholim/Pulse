from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class OmerloSettings(BaseSettings):
    """Connection settings for the Omerlo backoffice API, read from OMERLO_* variables."""

    model_config = SettingsConfigDict(env_prefix="OMERLO_", extra="ignore")

    # Includes the /api prefix, e.g. https://ca.omerlo.app/api
    base_url: HttpUrl
    api_key: SecretStr
    timeout_seconds: float = 30.0
