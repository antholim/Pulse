import uuid

import pytest

from app.storage.archive import ArchiveAccessError, ArchiveNotFoundError, archive_key
from app.storage.local import LocalArchive

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
RUN = uuid.UUID("33333333-3333-3333-3333-333333333333")
DIGEST = "b" * 64
DATA = b'{"id":"org-1"}'


@pytest.fixture
def archive(tmp_path):
    return LocalArchive(tmp_path / "archive")


def test_put_writes_the_bytes_under_the_key_and_get_reads_them_back(archive):
    # Arrange
    key = archive_key(TENANT, RUN, "organization", DIGEST)

    # Act
    uri = archive.put(key, DATA)

    # Assert
    assert uri == (archive.root / key).as_uri()
    assert (archive.root / key).read_bytes() == DATA
    assert archive.get(uri, TENANT) == DATA


def test_put_of_an_existing_key_keeps_the_stored_file(archive):
    # Arrange
    key = archive_key(TENANT, RUN, "organization", DIGEST)
    archive.put(key, DATA)

    # Act
    archive.put(key, b"ignored")

    # Assert
    assert (archive.root / key).read_bytes() == DATA
    assert [p.name for p in (archive.root / key).parent.iterdir()] == [f"{DIGEST}.json"]


def test_put_cleans_up_the_temporary_file_when_writing_fails(archive, mocker):
    # Arrange
    key = archive_key(TENANT, RUN, "organization", DIGEST)
    mocker.patch("app.storage.local.os.replace", side_effect=OSError("disk full"))

    # Act
    with pytest.raises(OSError):
        archive.put(key, DATA)

    # Assert
    assert list((archive.root / key).parent.iterdir()) == []


def test_get_rejects_another_tenants_payload(archive):
    # Arrange
    uri = archive.put(archive_key(OTHER_TENANT, RUN, "organization", DIGEST), DATA)

    # Act / Assert
    with pytest.raises(ArchiveAccessError):
        archive.get(uri, TENANT)


@pytest.mark.parametrize(
    "uri",
    [
        f"s3://bucket/tenants/{TENANT}/runs/{RUN}/organization/{DIGEST}.json",
        f"file://evil.example/tenants/{TENANT}/runs/{RUN}/organization/{DIGEST}.json",
        "file:///etc/passwd",
    ],
)
def test_get_rejects_uris_outside_the_archive(archive, uri):
    # Act / Assert
    with pytest.raises(ArchiveAccessError):
        archive.get(uri, TENANT)


def test_get_rejects_path_traversal_out_of_the_tenant_folder(archive):
    # Arrange
    other = archive.put(archive_key(OTHER_TENANT, RUN, "organization", DIGEST), DATA)
    sneaky = (
        f"{archive.root.as_uri()}/tenants/{TENANT}/runs/{RUN}/organization/../../../../"
        f"{other.removeprefix(archive.root.as_uri() + '/')}"
    )

    # Act / Assert
    with pytest.raises(ArchiveAccessError):
        archive.get(sneaky, TENANT)


def test_get_rejects_a_symlink_to_another_tenants_file(archive):
    # Arrange
    other = archive.root / archive_key(OTHER_TENANT, RUN, "organization", DIGEST)
    archive.put(archive_key(OTHER_TENANT, RUN, "organization", DIGEST), DATA)
    link = archive.root / archive_key(TENANT, RUN, "organization", DIGEST)
    link.parent.mkdir(parents=True)
    link.symlink_to(other)

    # Act / Assert
    with pytest.raises(ArchiveAccessError):
        archive.get(link.as_uri(), TENANT)


def test_get_of_a_missing_payload_raises_not_found(archive):
    # Arrange
    uri = (archive.root / archive_key(TENANT, RUN, "organization", DIGEST)).as_uri()

    # Act / Assert
    with pytest.raises(ArchiveNotFoundError):
        archive.get(uri, TENANT)
