import uuid
from typing import Any
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError

from app.storage.archive import (
    ArchiveAccessError,
    ArchiveError,
    ArchiveNotFoundError,
    check_key,
)

NOT_FOUND_CODES = {"NoSuchKey", "404", "NotFound"}


class S3Archive:
    """Archive in an S3-compatible bucket (Tigris on Fly.io). URIs are `s3://bucket/key`."""

    def __init__(self, bucket: str, client: Any) -> None:
        self.bucket = bucket
        self._client = client

    def put(self, key: str, data: bytes) -> str:
        try:
            self._client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType="application/json"
            )
        except (BotoCoreError, ClientError) as error:
            raise ArchiveError(f"Could not archive payload {key}: {error}") from error
        return f"s3://{self.bucket}/{key}"

    def get(self, uri: str, tenant_id: uuid.UUID) -> bytes:
        parts = urlsplit(uri)
        if parts.scheme != "s3" or parts.netloc != self.bucket:
            raise ArchiveAccessError("Archived payload is outside this tenant's archive")
        key = check_key(parts.path.removeprefix("/"), tenant_id)
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in NOT_FOUND_CODES:
                raise ArchiveNotFoundError(f"Archived payload not found: {key}") from None
            raise ArchiveError(f"Could not read archived payload {key}: {error}") from error
        except BotoCoreError as error:
            raise ArchiveError(f"Could not read archived payload {key}: {error}") from error
