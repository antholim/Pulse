"""Shapes of the Omerlo Reader API resources, used to validate synthetic fixtures.

Organization, Person and Content follow the fields documented on
developers.omerlo.com. Event, Project, Category, ProfileType and the content
blocks are not fully documented; their shapes are assumptions to check on
staging (#23). Unknown fields are rejected, so a typo in the generator fails
validation instead of producing silently wrong fixtures.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Address(Strict):
    street: str | None
    location: str | None
    city: str | None
    state: str | None
    country: str | None


class Contact(Strict):
    email: str | None
    phone: str | None
    linkedin: str | None
    website: str | None
    facebook: str | None
    instagram: str | None
    twitter: str | None
    bluesky: str | None


class MetadataEntry(Strict):
    key: str
    value: str


class Meta(Strict):
    locales: list[str]


class ProfileRef(Strict):
    kind: Literal["organization", "person"]
    id: str


# Assumed block shape: a paragraph of text, or a Profiles block linking profiles.
class Block(Strict):
    kind: Literal["paragraph", "profiles"]
    text: str | None = None
    profiles: list[ProfileRef] | None = None


class Description(Strict):
    blocks: list[Block]


class Visual(Strict):
    url: str
    caption: str | None


class Organization(Strict):
    id: str
    profile_type_id: str
    name: str
    summary_text: str | None
    canonical_url: str | None
    canonical_domain: str | None
    address: Address
    description: Description
    contact: Contact
    category_ids: list[str]
    metadata: list[MetadataEntry]
    meta: Meta
    updated_at: str


class Person(Strict):
    id: str
    profile_type_id: str
    first_name: str
    last_name: str
    other_name: str | None
    pronoun: str | None
    job_title: str | None
    canonical_url: str | None
    address: Address
    contact: Contact
    category_ids: list[str]
    metadata: list[MetadataEntry]
    updated_at: str


class Content(Strict):
    """A content as returned by the detail endpoint; the list endpoint omits `blocks`."""

    id: str
    template_id: str
    title_text: str
    lead_text: str | None
    subtitle_text: str | None
    canonical_url: str
    visibility: Literal["public", "subscribers"]
    is_advertising: bool
    is_sponsored: bool
    published_at: str
    author_ids: list[str]
    category_ids: list[str]
    visual: Visual | None
    blocks: list[Block]
    updated_at: str


class Event(Strict):
    id: str
    name: str
    summary_text: str | None
    canonical_url: str
    starts_at: str
    ends_at: str
    address: Address
    category_ids: list[str]
    organizer_ids: list[str]
    updated_at: str


class Project(Strict):
    id: str
    name: str
    summary_text: str | None
    canonical_url: str
    organization_ids: list[str]
    category_ids: list[str]
    updated_at: str


class Category(Strict):
    id: str
    name: str
    slug: str


class ProfileType(Strict):
    id: str
    name: str
    kind: Literal["organization", "person"]
    # Metadata keys this profile type carries, e.g. a CRM id used as an external id.
    metadata_keys: list[str]


# One fixture file per entity kind, named after the kind.
MODELS: dict[str, type[Strict]] = {
    "categories": Category,
    "profile_types": ProfileType,
    "organizations": Organization,
    "people": Person,
    "projects": Project,
    "events": Event,
    "contents": Content,
}


def write_json_schemas(out_dir: Path) -> list[Path]:
    """Write one JSON Schema file per resource, for tools outside Python."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, model in MODELS.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n")
        paths.append(path)
    return paths
