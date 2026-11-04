# AI contribution: 50% or more AI-generated
"""Read a CSV or JSON import file into numbered rows of text values."""

import csv
import io
import json
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from app.core.errors import DataValidationError
from app.ingestion.files.columns import FileLayout

FORMATS = {".csv": "csv", ".json": "json"}


class ImportFileError(DataValidationError):
    """The whole file cannot be imported, e.g. it is not UTF-8 or lacks a required column."""


@dataclass(frozen=True)
class FileRow:
    # The spreadsheet row of a CSV line (the header is row 1), or the position of a JSON entry.
    number: int
    values: dict[str, str | None]
    # Why the row cannot be read, found before any validation.
    problem: str | None = None


def file_format(name: str) -> str:
    suffix = PurePath(name).suffix.lower()
    if suffix not in FORMATS:
        raise ImportFileError("only .csv and .json files can be imported")
    return FORMATS[suffix]


def read_file(data: bytes, file_format: str, layout: FileLayout) -> list[FileRow]:
    text = decode(data)
    if file_format == "json":
        return read_json(text)
    return read_csv(text, layout)


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportFileError("file is not UTF-8; save it as CSV UTF-8") from None


def read_csv(text: str, layout: FileLayout) -> list[FileRow]:
    if not text.strip():
        raise ImportFileError("file is empty")
    first_line = text.splitlines()[0]
    # French spreadsheet exports separate values with semicolons.
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    lines = enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1)
    _, header_cells = next(lines)
    header = [cell.strip().lower() for cell in header_cells]
    check_header(header, layout)
    rows = []
    for number, cells in lines:
        if not any(cell.strip() for cell in cells):
            continue
        extra = cells[len(header) :]
        values = {name: clean(cell) for name, cell in zip(header, cells, strict=False) if name}
        values.update({name: None for name in header[len(cells) :] if name})
        problem = None
        if any(cell.strip() for cell in extra):
            problem = "row has more values than the header has columns"
        rows.append(FileRow(number, values, problem))
    return rows


def check_header(header: list[str], layout: FileLayout) -> None:
    names = [name for name in header if name]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ImportFileError("repeated column: " + ", ".join(repeated))
    missing = [name for name in layout.required if name not in names]
    if missing:
        raise ImportFileError("missing required columns: " + ", ".join(missing))
    if layout.one_of and not set(layout.one_of) & set(names):
        raise ImportFileError("needs one of the columns: " + ", ".join(layout.one_of))


def read_json(text: str) -> list[FileRow]:
    try:
        entries = json.loads(text)
    except json.JSONDecodeError:
        entries = None
    if not isinstance(entries, list):
        raise ImportFileError("file must be a JSON list of objects")
    rows = []
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            rows.append(FileRow(number, {}, "entry is not a JSON object"))
            continue
        values: dict[str, str | None] = {}
        problem = None
        for key, value in entry.items():
            name = str(key).strip().lower()
            if value is not None and not is_scalar(value):
                problem = problem or f"value of {name} is not text or a number"
                continue
            values[name] = None if value is None else clean(str(value))
        rows.append(FileRow(number, values, problem))
    return rows


def is_scalar(value: Any) -> bool:
    return isinstance(value, str) or (
        isinstance(value, int | float) and not isinstance(value, bool)
    )


def clean(value: str) -> str | None:
    return value.strip() or None
