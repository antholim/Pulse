"""Readers for Omerlo payload parts; a value of the wrong type reads as absent."""

import html
import re
from collections.abc import Iterable
from typing import Any

from app.ingestion.connector import parse_timestamp
from app.processing.normalization import (
    normalize_domain,
    normalize_email,
    normalize_linkedin,
    normalize_phone,
    normalize_text,
)

_HTML_TAG = re.compile(r"<[^>]+>")


def text(value: Any) -> str | None:
    """The value stripped, or None when it is not a non-blank string."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def html_text(value: Any) -> str | None:
    """The text of an HTML fragment such as a `title_html`."""
    raw = text(value)
    return text(html.unescape(_HTML_TAG.sub(" ", raw))) if raw else None


def flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def timestamp(value: Any) -> str | None:
    """An ISO 8601 timestamp as a UTC-aware ISO string, or None when invalid."""
    parsed = parse_timestamp(value)
    return parsed.isoformat() if parsed else None


def dicts(value: Any) -> list[dict[str, Any]]:
    """The objects of a JSON list, skipping anything else."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def live_entries(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """The entries of a per-locale list (`contact`, `address`, `locales`) not soft-deleted."""
    return [entry for entry in dicts(payload.get(key)) if entry.get("deleted_at") is None]


def unique(values: Iterable[str | None]) -> list[str]:
    """The non-null values in first-seen order, without duplicates."""
    return list(dict.fromkeys(value for value in values if value is not None))


def first(values: Iterable[str | None]) -> str | None:
    return next((value for value in values if value is not None), None)


def grouped(pairs: Iterable[tuple[str | None, str | None]]) -> dict[str, list[str]]:
    """Values by key in first-seen order, dropping pairs with a missing key or value."""
    groups: dict[str, list[str]] = {}
    for key, value in pairs:
        if key and value and value not in groups.setdefault(key, []):
            groups[key].append(value)
    return groups


def id_text(value: Any) -> str | None:
    """An id as a string; Omerlo ids are UUID strings, but integers are accepted."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return text(value)


def profile_workspace_id(payload: dict[str, Any]) -> str | None:
    profile = payload.get("profile")
    return id_text(profile.get("workspace_id")) if isinstance(profile, dict) else None


def contact_identifiers(payload: dict[str, Any]) -> dict[str, list[str]]:
    """Every email, phone, website domain and LinkedIn URL across locales, normalized."""
    contacts = live_entries(payload, "contact")

    def values(field: str) -> list[str | None]:
        return [text(contact.get(field)) for contact in contacts]

    return {
        "emails": unique(normalize_email(value) for value in values("email")),
        "phones": unique(normalize_phone(value).e164 for value in values("phone")),
        "domains": unique(normalize_domain(value) for value in values("website")),
        "linkedin": unique(normalize_linkedin(value) for value in values("linkedin")),
    }


def cities(payload: dict[str, Any]) -> list[str]:
    """The normalized city of every address, for the name plus city match."""
    return unique(normalize_text(text(a.get("city"))) for a in live_entries(payload, "address"))


def metadata_ids(entries: Any) -> dict[str, list[str]]:
    """Metadata key and value pairs as key to values, so a CRM id can be matched later."""
    return grouped((text(entry.get("key")), text(entry.get("value"))) for entry in dicts(entries))
