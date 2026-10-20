"""Shapes of the Omerlo backoffice API resources, used to validate synthetic fixtures.

Fields follow the backoffice documentation (developers.omerlo.com/docs/backoffice,
summarized on the wiki page "Omerlo API"). Detail models are what `GET .../{id}`
returns; summary models are what the list endpoints return, and `summarize`
derives one from the other. Unknown fields are rejected, so a typo in the
generator fails validation instead of producing silently wrong fixtures.

Two documented field names end in `?` (`all_day?`, `registration_open?`); they are
read as optional fields named without it.
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ profiles


class ProfileCategory(Strict):
    id: str
    category_id: str


class Profile(Strict):
    # The profile id is the id of the organization, person, event or project.
    id: str
    workspace_id: str
    profile_categories: list[ProfileCategory]
    profile_type_id: str
    status_id: str
    canonical_url: str | None


class ProfileSummary(Strict):
    id: str
    profile_type_id: str
    status_id: str
    canonical_url: str | None


class Contact(Strict):
    """One locale's contact details; a record has one entry per locale."""

    id: str
    locale: str
    email: str | None
    phone: str | None
    facebook: str | None
    linkedin: str | None
    instagram: str | None
    twitter: str | None
    bluesky: str | None
    website: str | None
    deleted_at: str | None


class Address(Strict):
    id: str
    locale: str
    country: str | None
    city: str | None
    street: str | None
    location: str | None
    deleted_at: str | None


class DescriptionBlock(Strict):
    kind: Literal["richtext", "html", "image", "slideshow", "video"]
    content_html: str | None
    content_text: str | None
    image: dict[str, Any] | None
    slideshow: dict[str, Any] | None
    video: dict[str, Any] | None


class Description(Strict):
    id: str
    locale: str
    blocks: list[DescriptionBlock]
    deleted_at: str | None


class MetadataEntry(Strict):
    """Key and value pair served by `GET /community/v2/<kind>/{id}/metadata`."""

    key: str
    value: str


class ProfileFields(Strict):
    """Fields shared by the detail shape of every community profile."""

    id: str
    profile_image_key: str | None
    cover_image_key: str | None
    profile: Profile
    description: list[Description]
    address: list[Address]
    contact: list[Contact]
    inserted_at: str
    updated_at: str


# --------------------------------------------------------------- organization


class OrganizationLocale(Strict):
    id: str
    locale: str
    summary_html: str | None
    deleted_at: str | None


class Organization(ProfileFields):
    name: str
    locales: list[OrganizationLocale]


class OrganizationSummary(Strict):
    id: str
    profile: ProfileSummary
    name: str
    profile_image_key: str | None
    inserted_at: str
    updated_at: str


# --------------------------------------------------------------------- person


class PersonLocale(Strict):
    id: str
    locale: str
    job_title: str | None
    summary_html: str | None
    deleted_at: str | None


class Person(ProfileFields):
    first_name: str
    last_name: str
    other_name: str | None
    pronoun: str | None
    locales: list[PersonLocale]


class PersonSummary(Strict):
    id: str
    profile: ProfileSummary
    first_name: str
    last_name: str
    other_name: str | None
    pronoun: str | None
    profile_image_key: str | None
    inserted_at: str
    updated_at: str


# ---------------------------------------------------------- event and project


class NamedLocale(Strict):
    id: str
    locale: str
    name: str
    summary_html: str | None
    deleted_at: str | None


class EventSummaryLocale(NamedLocale):
    description_html: str | None


class Schedule(Strict):
    id: str
    recurrence: Literal[
        "none", "daily", "weekly", "monthly", "last_of_month", "monthly_on", "yearly", "custom"
    ]
    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    interval: int
    starts_at_date: str
    starts_at_time: str
    ends_at_date: str
    ends_at_time: str
    all_day: bool | None = None
    count: int
    until: str | None
    timezone: str
    excluded_dates: list[str]
    days: list[str]
    monthly_opts: Literal["monthly", "monthly_on", "last_of_month"]


class FormBlockLocale(Strict):
    id: str
    locale: str
    content_html: str
    content_text: str


class FormBlock(Strict):
    id: str
    required: bool | None = None
    locales: list[FormBlockLocale]
    position: int


class Form(Strict):
    id: str
    blocks: list[FormBlock]


class Event(ProfileFields):
    subscription_url: str | None
    schedule: Schedule
    locales: list[NamedLocale]
    form: Form
    registration_open: bool | None = None
    registration_opens_at: str | None
    registration_closes_at: str | None
    registration_timezone: str | None


class EventSummary(Strict):
    id: str
    profile: ProfileSummary
    profile_image_key: str | None
    locales: list[EventSummaryLocale]
    inserted_at: str
    updated_at: str


class SessionLocale(Strict):
    id: str
    locale: str
    title_html: str
    description_html: str | None
    deleted_at: str | None


class SessionSpeaker(Strict):
    id: str
    position: int
    # Assumed to be a person id; to confirm on staging.
    actor_id: str


class EventSession(Strict):
    """Served by `GET /community/v2/events/{event_id}/sessions`."""

    id: str
    event_id: str
    location: str
    starts_at: str
    ends_at: str | None
    timezone: str
    locales: list[SessionLocale]
    session_speakers: list[SessionSpeaker]
    inserted_at: str
    updated_at: str


class Project(ProfileFields):
    # Assumed to be an organization id; the documentation does not say.
    owner_id: str | None
    locales: list[NamedLocale]


class ProjectSummary(Strict):
    id: str
    owner_id: str | None
    profile: ProfileSummary
    profile_image_key: str | None
    locales: list[NamedLocale]
    inserted_at: str
    updated_at: str


# ------------------------------------------------------- category, workspace


class CategoryLocale(Strict):
    id: str
    locale: str
    name: str
    description: str | None
    deleted_at: str | None


class Category(Strict):
    """Served by `GET /core/v2/categories`; one list per client, not per workspace."""

    id: str
    locales: list[CategoryLocale]
    svg_icon: str | None
    deleted_at: str | None
    is_archived: bool
    is_unlisted: bool
    inserted_at: str
    updated_at: str


class WorkspaceLocale(Strict):
    id: str
    locale: str
    description: str
    deleted_at: str | None


class StatusLocale(Strict):
    id: str
    locale: str
    name: str
    description: str | None
    deleted_at: str | None


class Status(Strict):
    id: str
    color: str
    text_color: str
    completed: bool
    locales: list[StatusLocale]
    position: int
    inserted_at: str
    updated_at: str


class Workspace(Strict):
    """Served by `GET /composer/v2/workspaces/{id}`; the list omits `statuses`."""

    id: str
    name: str
    canonical_domain: str
    locales: list[WorkspaceLocale]
    statuses: list[Status]
    inserted_at: str
    updated_at: str


class WorkspaceSummary(Strict):
    id: str
    name: str
    canonical_domain: str
    locales: list[WorkspaceLocale]
    inserted_at: str
    updated_at: str


# ------------------------------------------------------------------ registry

# One fixture file per entity kind, named after the kind, holding detail records.
MODELS: dict[str, type[Strict]] = {
    "workspaces": Workspace,
    "categories": Category,
    "organizations": Organization,
    "people": Person,
    "projects": Project,
    "events": Event,
    "event_sessions": EventSession,
}

# The shape list endpoints return, for the kinds whose list differs from the detail.
SUMMARY_MODELS: dict[str, type[Strict]] = {
    "workspaces": WorkspaceSummary,
    "organizations": OrganizationSummary,
    "people": PersonSummary,
    "projects": ProjectSummary,
    "events": EventSummary,
}

# Metadata is served apart from the record: entity id -> key and value entries.
METADATA_FILE = "metadata"


def summarize(kind: str, record: dict[str, Any]) -> dict[str, Any]:
    """The list endpoint's view of a detail record."""
    model = SUMMARY_MODELS.get(kind)
    if model is None:
        return record
    summary = {key: record[key] for key in model.model_fields if key in record}
    if "profile" in summary:
        summary["profile"] = {key: record["profile"][key] for key in ProfileSummary.model_fields}
    if kind == "events":
        summary["locales"] = [
            {**locale, "description_html": description_html(record, locale["locale"])}
            for locale in record["locales"]
        ]
    return summary


def description_html(record: dict[str, Any], locale: str) -> str | None:
    parts = [
        block["content_html"]
        for description in record["description"]
        if description["locale"] == locale
        for block in description["blocks"]
        if block["content_html"]
    ]
    return "".join(parts) or None


def write_json_schemas(out_dir: Path) -> list[Path]:
    """Write one JSON Schema file per resource and summary, for tools outside Python."""
    out_dir.mkdir(parents=True, exist_ok=True)
    models = {**MODELS, **{f"{k}.summary": m for k, m in SUMMARY_MODELS.items()}}
    models[METADATA_FILE] = MetadataEntry
    paths = []
    for name, model in models.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n")
        paths.append(path)
    return paths
