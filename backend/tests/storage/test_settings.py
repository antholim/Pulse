import pytest
from pydantic import ValidationError

from app.storage.local import LocalArchive
from app.storage.s3 import S3Archive
from app.storage.settings import ArchiveSettings, create_archive


@pytest.fixture(autouse=True)
def no_archive_variables(monkeypatch):
    for name in ("BACKEND", "DIR", "BUCKET", "S3_ENDPOINT_URL", "S3_REGION"):
        monkeypatch.delenv(f"ARCHIVE_{name}", raising=False)


def test_local_folder_is_the_default(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path))

    # Act
    archive = create_archive()

    # Assert
    assert isinstance(archive, LocalArchive)
    assert archive.root == tmp_path.resolve()


def test_s3_backend_uses_the_configured_bucket_and_endpoint(monkeypatch):
    # Arrange
    monkeypatch.setenv("ARCHIVE_BACKEND", "s3")
    monkeypatch.setenv("ARCHIVE_BUCKET", "pulse-archive")
    monkeypatch.setenv("ARCHIVE_S3_ENDPOINT_URL", "https://fly.storage.tigris.dev")
    monkeypatch.setenv("ARCHIVE_S3_REGION", "auto")
    monkeypatch.setenv("ARCHIVE_S3_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("ARCHIVE_S3_SECRET_ACCESS_KEY", "s3cret")

    # Act
    settings = ArchiveSettings()
    archive = create_archive(settings)

    # Assert
    assert isinstance(archive, S3Archive)
    assert archive.bucket == "pulse-archive"
    assert archive._client.meta.endpoint_url == "https://fly.storage.tigris.dev"
    assert "s3cret" not in repr(settings)


def test_s3_backend_requires_a_bucket(monkeypatch):
    # Arrange
    monkeypatch.setenv("ARCHIVE_BACKEND", "s3")

    # Act / Assert
    with pytest.raises(ValidationError, match="ARCHIVE_BUCKET"):
        ArchiveSettings()


def test_unknown_backend_is_rejected(monkeypatch):
    # Arrange
    monkeypatch.setenv("ARCHIVE_BACKEND", "ftp")

    # Act / Assert
    with pytest.raises(ValidationError):
        ArchiveSettings()
