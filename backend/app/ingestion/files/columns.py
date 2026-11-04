# AI contribution: 50% or more AI-generated
"""The columns an import file may have for each entity kind, and their template files."""

from dataclasses import dataclass
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class FileLayout:
    kind: str
    columns: tuple[str, ...]
    # Columns every row must fill.
    required: tuple[str, ...]
    # Columns of which every row must fill at least one.
    one_of: tuple[str, ...] = ()


LAYOUTS = {
    "organization": FileLayout(
        kind="organization",
        columns=("id", "name", "website", "linkedin", "email", "phone", "city", "address"),
        required=("id", "name"),
    ),
    "person": FileLayout(
        kind="person",
        columns=(
            "id",
            "first_name",
            "last_name",
            "email",
            "linkedin",
            "job_title",
            "organization_id",
        ),
        required=("id",),
        one_of=("first_name", "last_name"),
    ),
}

TEMPLATES = {
    "organization": TEMPLATE_DIR / "organizations.csv",
    "person": TEMPLATE_DIR / "people.csv",
}
