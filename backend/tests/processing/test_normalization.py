"""Tests for the normalization skeleton and shared helpers (#26)."""

import pytest

from app.processing import normalization as norm
from app.processing.normalization import (
    CONNECTOR_ALIASES,
    CONNECTOR_TOKEN,
    DEFAULT_PHONE_REGION,
    LINKEDIN_HOSTS,
    PhoneResult,
    email_domain,
    legal_suffixes,
    normalize_domain,
    normalize_email,
    normalize_linkedin,
    normalize_organization_name,
    normalize_person_name,
    normalize_phone,
)


def test_default_phone_region_is_canada():
    assert DEFAULT_PHONE_REGION == "CA"


def test_linkedin_hosts_cover_www_and_apex():
    assert "linkedin.com" in LINKEDIN_HOSTS
    assert "www.linkedin.com" in LINKEDIN_HOSTS


def test_connector_aliases_map_to_one_token():
    assert frozenset({"&", "et", "and"}) == CONNECTOR_ALIASES
    assert CONNECTOR_TOKEN == "and"


def test_fold_accents_is_deterministic():
    assert norm._fold_accents("Québec") == "Quebec"
    assert norm._fold_accents("Québec") == norm._fold_accents("Québec")
    assert norm._fold_accents("Marie-Ève") == "Marie-Eve"


def test_collapse_whitespace_trims_and_squeezes():
    assert norm._collapse_whitespace("  foo   bar\t") == "foo bar"
    assert norm._collapse_whitespace("already neat") == "already neat"


def test_legal_suffixes_include_quebec_and_english_forms():
    suffixes = legal_suffixes()

    assert "inc" in suffixes
    assert "ltee" in suffixes  # folded from ltée
    assert "limitee" in suffixes
    assert "senc" in suffixes
    assert "s e n c" in suffixes  # s.e.n.c. after punctuation cleanup
    assert "coop" in suffixes
    assert "cooperative" in suffixes
    assert "corp" in suffixes
    assert "sa" in suffixes
    assert "llc" in suffixes
    assert "gmbh" in suffixes


def test_legal_suffixes_loader_is_cached():
    first = legal_suffixes()
    second = legal_suffixes()
    assert first is second


@pytest.mark.parametrize(
    ("function", "args", "expected"),
    [
        (normalize_organization_name, (None,), None),
        (normalize_organization_name, ("Groupe Exemple ltée",), None),
        (normalize_person_name, (None,), None),
        (normalize_person_name, ("Marie-Ève Tremblay",), None),
        (normalize_domain, (None,), None),
        (normalize_domain, ("https://www.exemple.qc.ca",), None),
        (normalize_linkedin, (None,), None),
        (normalize_email, (None,), None),
        (email_domain, (None,), None),
    ],
)
def test_public_normalizer_stubs_return_none(function, args, expected):
    assert function(*args) == expected


def test_phone_stub_returns_empty_result():
    result = normalize_phone("+1 418 555 0100")

    assert isinstance(result, PhoneResult)
    assert result.e164 is None
    assert result.warnings == ()
