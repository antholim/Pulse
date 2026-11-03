# AI contribution: 50% or more AI-generated
"""A connector that reads one CSV or JSON file of organizations or people."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime

from app.ingestion.connector import RawRecord
from app.ingestion.files.columns import LAYOUTS
from app.ingestion.files.reader import FileRow, ImportFileError, file_format, read_file
from app.ingestion.mapped import MappingFailure
from app.processing.normalization import (
    normalize_domain,
    normalize_email,
    normalize_linkedin,
    normalize_phone,
)

# A filled value must normalize to something, or the row is rejected.
FORMAT_CHECKS: dict[str, tuple[Callable[[str], object], str]] = {
    "website": (normalize_domain, "website is not a web address"),
    "linkedin": (normalize_linkedin, "linkedin is not a LinkedIn company or profile URL"),
    "email": (normalize_email, "email is not an email address"),
    "phone": (lambda value: normalize_phone(value).e164, "phone is not a phone number"),
}


@dataclass(frozen=True)
class RejectedRow:
    row: int
    reason: str
    id: str | None


class FileConnector:
    kind = "csv"

    def __init__(self, data: bytes, name: str, entity_kind: str) -> None:
        if entity_kind not in LAYOUTS:
            raise ImportFileError(f"cannot import {entity_kind} files")
        self.layout = LAYOUTS[entity_kind]
        self.rows = read_file(data, file_format(name), self.layout)
        self.rejected: list[RejectedRow] = []

    def fetch_since(self, watermark: datetime | None) -> Iterator[RawRecord]:
        """Yield every valid row; a file has no update times, so the watermark is ignored."""
        self.rejected = []
        first_row: dict[str, int] = {}
        kind = self.layout.kind
        for row in self.rows:
            record_id = row.values.get("id")
            reason = self.invalid(row)
            if reason is None and record_id in first_row:
                reason = f"id {record_id} is already used on row {first_row[record_id]}"
            if reason is not None:
                self.rejected.append(RejectedRow(row.number, reason, record_id))
                continue
            first_row[record_id] = row.number
            yield RawRecord(kind, external_id(kind, record_id), None, dict(row.values))

    def invalid(self, row: FileRow) -> str | None:
        """Why the row cannot be imported, or None when it is valid."""
        if row.problem:
            return row.problem
        values = row.values
        for name in self.layout.required:
            if not values.get(name):
                return f"{name} is missing"
        if self.layout.one_of and not any(values.get(name) for name in self.layout.one_of):
            return " or ".join(self.layout.one_of) + " is needed"
        for name, (normalize, reason) in FORMAT_CHECKS.items():
            value = values.get(name)
            if value and not normalize(value):
                return reason
        return None

    def failures(self) -> list[MappingFailure]:
        """The rejected rows of the last read, as failures of the sync run."""
        kind = self.layout.kind
        return [
            MappingFailure(
                kind,
                external_id(kind, rejected.id) if rejected.id else f"row {rejected.row}",
                f"row {rejected.row}: {rejected.reason}",
            )
            for rejected in self.rejected
        ]


def external_id(kind: str, record_id: str) -> str:
    """Ids are only unique within one kind of file, and one source can hold several kinds."""
    return f"{kind}:{record_id}"
