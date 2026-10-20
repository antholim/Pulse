"""Identifier normalization for Entity Resolution (#26).

Pure string-to-key helpers used before matching. Callers (for example the Omerlo
mapper in #57) extract fields from source payloads and pass them here; this
module never reads the database or the network.

Libraries (Infrastructure and Tools wiki): phonenumbers, tldextract, unicodedata.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Default region for numbers without a country code (wiki + #26 AC).
DEFAULT_PHONE_REGION = "CA"

# Hosts treated as LinkedIn when normalizing profile URLs.
LINKEDIN_HOSTS = frozenset({"linkedin.com", "www.linkedin.com"})

# Ampersand / conjunction variants collapsed to one token for org-name keys.
CONNECTOR_TOKEN = "and"
CONNECTOR_ALIASES = frozenset({"&", "et", "and"})

_LEGAL_SUFFIXES_PATH = Path(__file__).with_name("legal_suffixes.toml")

# Punctuation and symbols become spaces before whitespace is collapsed.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class PhoneResult:
    """Outcome of phone normalization: E.164 value or null, plus warnings."""

    e164: str | None
    warnings: tuple[str, ...] = ()


def _fold_accents(value: str) -> str:
    """Drop diacritics: ``Québec`` becomes ``Quebec`` (case preserved)."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _collapse_whitespace(value: str) -> str:
    """Trim and collapse runs of whitespace to a single space."""
    return _WHITESPACE.sub(" ", value.strip())


def _suffix_match_forms(raw: str) -> frozenset[str]:
    """Forms of a legal suffix used for end-of-name matching after name cleanup."""
    folded = _fold_accents(raw).lower()
    spaced = _collapse_whitespace(_NON_ALNUM.sub(" ", folded))
    compact = spaced.replace(" ", "")
    forms = {spaced, compact} - {""}
    return frozenset(forms)


@lru_cache(maxsize=1)
def _load_legal_suffixes() -> frozenset[str]:
    """Load and normalize legal suffixes from ``legal_suffixes.toml`` once."""
    with _LEGAL_SUFFIXES_PATH.open("rb") as handle:
        data = tomllib.load(handle)
    raw_suffixes = data.get("suffixes", [])
    if not isinstance(raw_suffixes, list) or not raw_suffixes:
        raise ValueError(f"{_LEGAL_SUFFIXES_PATH.name} must define a non-empty suffixes list")

    forms: set[str] = set()
    for entry in raw_suffixes:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(
                f"invalid legal suffix entry in {_LEGAL_SUFFIXES_PATH.name}: {entry!r}"
            )
        forms.update(_suffix_match_forms(entry))
    return frozenset(forms)


def legal_suffixes() -> frozenset[str]:
    """Public read-only view of the loaded legal-suffix match forms."""
    return _load_legal_suffixes()


def normalize_organization_name(value: str | None) -> str | None:
    """Return a comparison key for an organization name, or None if unusable."""
    return None


def normalize_person_name(value: str | None) -> str | None:
    """Return a comparison key for a person full name, or None if unusable."""
    return None


def normalize_domain(value: str | None) -> str | None:
    """Return the registered domain for a URL or host, or None if unusable."""
    return None


def normalize_linkedin(value: str | None) -> str | None:
    """Return ``company/<slug>`` or ``in/<slug>``, or None if unusable."""
    return None


def normalize_email(value: str | None) -> str | None:
    """Return a lowercased email address, or None if unusable."""
    return None


def email_domain(value: str | None) -> str | None:
    """Return the domain part of an email, or None if unusable."""
    return None


def normalize_phone(value: str | None) -> PhoneResult:
    """Return an E.164 phone number, or null with warnings when invalid."""
    return PhoneResult(e164=None, warnings=())
