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
from urllib.parse import unquote, urlsplit

import phonenumbers
import tldextract
from phonenumbers import NumberParseException, PhoneNumberFormat

# Default region for numbers without a country code (wiki + #26 AC).
DEFAULT_PHONE_REGION = "CA"

# Reject absurdly long inputs before tokenization / library parsing.
MAX_IDENTIFIER_LENGTH = 2048

# Warning codes returned on PhoneResult when E.164 cannot be produced.
PHONE_WARNING_EMPTY = "empty"
PHONE_WARNING_UNPARSEABLE = "unparseable"
PHONE_WARNING_IMPOSSIBLE = "impossible"

# Apex host for LinkedIn; country subdomains like fr.linkedin.com also match.
LINKEDIN_APEX_HOST = "linkedin.com"
LINKEDIN_HOSTS = frozenset({"linkedin.com", "www.linkedin.com"})
LINKEDIN_PROFILE_KINDS = frozenset({"company", "in"})

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


@lru_cache(maxsize=1)
def _max_suffix_token_count() -> int:
    """Longest legal suffix in whitespace-separated tokens (for end matching)."""
    longest = 1
    for form in _load_legal_suffixes():
        if " " in form:
            longest = max(longest, len(form.split()))
    return longest


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > MAX_IDENTIFIER_LENGTH:
        return None
    return stripped


def _tokenize_name(value: str) -> list[str]:
    """Fold, lowercase, strip punctuation, collapse connectors into tokens."""
    folded = _fold_accents(value).lower()
    # Keep "&" visible as a token before non-alnum is wiped.
    folded = folded.replace("&", f" {CONNECTOR_TOKEN} ")
    spaced = _collapse_whitespace(_NON_ALNUM.sub(" ", folded))
    if not spaced:
        return []
    tokens: list[str] = []
    for token in spaced.split(" "):
        if token in CONNECTOR_ALIASES:
            tokens.append(CONNECTOR_TOKEN)
        else:
            tokens.append(token)
    return tokens


def _strip_trailing_legal_suffixes(tokens: list[str]) -> list[str]:
    """Remove trailing legal forms until none remain at the end."""
    suffixes = _load_legal_suffixes()
    max_k = min(len(tokens), _max_suffix_token_count())
    while tokens:
        stripped = False
        for k in range(min(len(tokens), max_k), 0, -1):
            candidate = " ".join(tokens[-k:])
            compact = "".join(tokens[-k:])
            if candidate in suffixes or compact in suffixes:
                tokens = tokens[:-k]
                stripped = True
                break
        if not stripped:
            break
    return tokens


def normalize_organization_name(value: str | None) -> str | None:
    """Return a comparison key for an organization name, or None if unusable."""
    raw = _blank_to_none(value)
    if raw is None:
        return None
    tokens = _strip_trailing_legal_suffixes(_tokenize_name(raw))
    if not tokens:
        return None
    return " ".join(tokens)


def normalize_person_name(value: str | None) -> str | None:
    """Return a comparison key for a person full name, or None if unusable."""
    raw = _blank_to_none(value)
    if raw is None:
        return None
    # Hyphens become spaces so Marie-Ève and Marie Eve share a key.
    folded = _fold_accents(raw).lower().replace("-", " ")
    spaced = _collapse_whitespace(_NON_ALNUM.sub(" ", folded))
    return spaced or None


@lru_cache(maxsize=1)
def _domain_extractor() -> tldextract.TLDExtract:
    """Public-suffix extractor that never fetches (bundled snapshot only)."""
    return tldextract.TLDExtract(suffix_list_urls=())


def normalize_domain(value: str | None) -> str | None:
    """Return the registered domain for a URL or host, or None if unusable."""
    raw = _blank_to_none(value)
    if raw is None or "@" in raw:
        # Emails are handled by normalize_email / email_domain, not here.
        return None
    extracted = _domain_extractor()(raw.strip().lower())
    domain = extracted.top_domain_under_public_suffix
    return domain.lower() if domain else None


def _is_linkedin_host(host: str) -> bool:
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host == LINKEDIN_APEX_HOST or host.endswith(f".{LINKEDIN_APEX_HOST}")


def _normalize_linkedin_slug(raw_slug: str) -> str | None:
    """Decode and validate a LinkedIn vanity slug.

    Accepts Unicode letters (including accents), digits and hyphens. Percent-
    encoded slugs such as ``marie-%C3%A8ve`` become ``marie-ève``.
    """
    slug = unquote(raw_slug.strip()).casefold()
    if (
        not slug
        or slug.startswith("-")
        or slug.endswith("-")
        or any(char.isspace() for char in slug)
        or not all(char == "-" or char.isalnum() for char in slug)
    ):
        return None
    return slug


def _linkedin_from_path(path: str) -> str | None:
    """Pull ``company/<slug>`` or ``in/<slug>`` from a URL path."""
    # Defense in depth: path-only callers may still pass query/fragment junk.
    path = path.split("?", 1)[0].split("#", 1)[0]
    parts = [part for part in path.split("/") if part]
    for index, part in enumerate(parts):
        if part in LINKEDIN_PROFILE_KINDS and index + 1 < len(parts):
            slug = _normalize_linkedin_slug(parts[index + 1])
            if slug:
                return f"{part}/{slug}"
    return None


def normalize_linkedin(value: str | None) -> str | None:
    """Return ``company/<slug>`` or ``in/<slug>``, or None if unusable."""
    raw = _blank_to_none(value)
    if raw is None:
        return None
    lowered = raw.lower()
    if "://" in lowered or lowered.startswith("//"):
        parsed = urlsplit(lowered if "://" in lowered else f"https:{lowered}")
        host = parsed.hostname or ""
        if not _is_linkedin_host(host):
            return None
        return _linkedin_from_path(parsed.path)

    # Host without scheme: ``linkedin.com/company/acme`` (reject other hosts).
    parsed = urlsplit(f"https://{lowered}")
    host = parsed.hostname or ""
    if host and "." in host:
        if not _is_linkedin_host(host):
            return None
        return _linkedin_from_path(parsed.path)

    # Path-only inputs such as ``/fr/company/acme`` or ``company/acme``.
    # urlsplit separates ?query and #fragment that full-URL parsing already drops.
    path_part = urlsplit(lowered if lowered.startswith("/") else f"/{lowered}").path
    return _linkedin_from_path(path_part)


def normalize_email(value: str | None) -> str | None:
    """Return a lowercased email address, or None if unusable."""
    raw = _blank_to_none(value)
    if raw is None:
        return None
    email = raw.strip().lower()
    if email.count("@") != 1 or any(char.isspace() for char in email):
        return None
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return None
    return email


def email_domain(value: str | None) -> str | None:
    """Return the domain part of an email, or None if unusable."""
    email = normalize_email(value)
    if email is None:
        return None
    return email.partition("@")[2]


def normalize_phone(value: str | None) -> PhoneResult:
    """Return an E.164 phone number, or null with warnings when invalid.

    Uses ``is_possible_number`` (not ``is_valid_number``) so synthetic 555
    exchanges still format for fixture tests. Never raises to callers.
    """
    if value is None or not value.strip():
        return PhoneResult(e164=None, warnings=(PHONE_WARNING_EMPTY,))

    raw = value.strip()
    if len(raw) > MAX_IDENTIFIER_LENGTH:
        return PhoneResult(e164=None, warnings=(PHONE_WARNING_UNPARSEABLE,))

    try:
        parsed = phonenumbers.parse(raw, DEFAULT_PHONE_REGION)
    except NumberParseException:
        return PhoneResult(e164=None, warnings=(PHONE_WARNING_UNPARSEABLE,))

    if not phonenumbers.is_possible_number(parsed):
        return PhoneResult(e164=None, warnings=(PHONE_WARNING_IMPOSSIBLE,))

    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    return PhoneResult(e164=e164, warnings=())
