import io
import uuid

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.storage.archive import (
    ArchiveAccessError,
    ArchiveError,
    ArchiveNotFoundError,
    archive_key,
)
from app.storage.s3 import S3Archive

BUCKET = "pulse-archive"
TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
RUN = uuid.UUID("33333333-3333-3333-3333-333333333333")
DIGEST = "c" * 64
DATA = b'{"id":"org-1"}'
KEY = archive_key(TENANT, RUN, "organization", DIGEST)


@pytest.fixture
def client():
    # Stubbed: no request leaves the process.
    return boto3.client(
        "s3",
        region_name="auto",
        endpoint_url="https://fly.storage.tigris.dev",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture
def stub(client):
    with Stubber(client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


@pytest.fixture
def archive(client):
    return S3Archive(BUCKET, client)


def test_put_uploads_the_bytes_under_the_key(archive, stub):
    # Arrange
    stub.add_response(
        "put_object",
        {},
        {"Bucket": BUCKET, "Key": KEY, "Body": DATA, "ContentType": "application/json"},
    )

    # Act
    uri = archive.put(KEY, DATA)

    # Assert
    assert uri == f"s3://{BUCKET}/{KEY}"


def test_put_wraps_storage_errors(archive, stub):
    # Arrange
    stub.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)

    # Act / Assert
    with pytest.raises(ArchiveError, match="Could not archive"):
        archive.put(KEY, DATA)


def test_get_reads_the_object_back(archive, stub):
    # Arrange
    body = StreamingBody(io.BytesIO(DATA), len(DATA))
    stub.add_response("get_object", {"Body": body}, {"Bucket": BUCKET, "Key": KEY})

    # Act
    data = archive.get(f"s3://{BUCKET}/{KEY}", TENANT)

    # Assert
    assert data == DATA


def test_get_of_a_missing_object_raises_not_found(archive, stub):
    # Arrange
    stub.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)

    # Act / Assert
    with pytest.raises(ArchiveNotFoundError):
        archive.get(f"s3://{BUCKET}/{KEY}", TENANT)


def test_get_wraps_other_storage_errors(archive, stub):
    # Arrange
    stub.add_client_error("get_object", service_error_code="SlowDown", http_status_code=503)

    # Act / Assert
    with pytest.raises(ArchiveError, match="Could not read"):
        archive.get(f"s3://{BUCKET}/{KEY}", TENANT)


@pytest.mark.parametrize(
    "uri",
    [
        f"s3://{BUCKET}/{archive_key(OTHER_TENANT, RUN, 'organization', DIGEST)}",
        f"s3://other-bucket/{KEY}",
        f"file:///{KEY}",
        f"s3://{BUCKET}/tenants/{TENANT}/runs/{RUN}/../../../tenants/{OTHER_TENANT}/x.json",
    ],
)
def test_get_rejects_uris_outside_the_tenants_prefix_without_calling_storage(archive, stub, uri):
    # Act / Assert: the stubber fails the test if any request is made.
    with pytest.raises(ArchiveAccessError):
        archive.get(uri, TENANT)
