from pathlib import Path
from typing import Literal

import boto3
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.storage.archive import PayloadArchive
from app.storage.local import LocalArchive
from app.storage.s3 import S3Archive


class ArchiveSettings(BaseSettings):
    """Where raw payloads are archived, read from ARCHIVE_* variables."""

    model_config = SettingsConfigDict(env_prefix="ARCHIVE_", extra="ignore")

    backend: Literal["local", "s3"] = "local"
    dir: Path = Path("raw-archive")
    bucket: str | None = None
    # Unset values fall back to boto3's defaults (AWS_* variables, as Fly sets for Tigris).
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None

    @model_validator(mode="after")
    def _bucket_for_s3(self) -> "ArchiveSettings":
        if self.backend == "s3" and not self.bucket:
            raise ValueError("ARCHIVE_BUCKET is required when ARCHIVE_BACKEND=s3")
        return self


def create_archive(settings: ArchiveSettings | None = None) -> PayloadArchive:
    settings = settings or ArchiveSettings()
    if settings.backend == "local":
        return LocalArchive(settings.dir)
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=_secret(settings.s3_access_key_id),
        aws_secret_access_key=_secret(settings.s3_secret_access_key),
    )
    return S3Archive(settings.bucket or "", client)


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value else None
