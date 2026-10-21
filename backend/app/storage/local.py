import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.storage.archive import (
    ArchiveAccessError,
    ArchiveNotFoundError,
    check_key,
    tenant_prefix,
)


class LocalArchive:
    """Archive in a local folder, for development. URIs are `file://` URIs."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def put(self, key: str, data: bytes) -> str:
        path = self.root / key
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write then rename, so a reader never sees a partial file.
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as file:
                    file.write(data)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return path.as_uri()

    def get(self, uri: str, tenant_id: uuid.UUID) -> bytes:
        parts = urlsplit(uri)
        if parts.scheme != "file" or parts.netloc not in ("", "localhost"):
            raise ArchiveAccessError("Archived payload is outside this tenant's archive")
        path = Path(unquote(parts.path))
        try:
            key = path.relative_to(self.root).as_posix()
        except ValueError:
            raise ArchiveAccessError("Archived payload is outside this tenant's archive") from None
        check_key(key, tenant_id)
        # A symlink inside the folder must not lead to another tenant's files.
        if not path.resolve().is_relative_to(self.root / tenant_prefix(tenant_id)):
            raise ArchiveAccessError("Archived payload is outside this tenant's archive")
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise ArchiveNotFoundError(f"Archived payload not found: {key}") from None
