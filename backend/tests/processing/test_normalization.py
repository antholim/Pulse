"""Tests for identifier normalization (#26)."""

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
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("Inc.", None),
        ("ltée", None),
        ("Groupe Exemple ltée", "groupe exemple"),
        ("GROUPE EXEMPLE", "groupe exemple"),
        ("Groupe Exemple Inc.", "groupe exemple"),
        ("Groupe Exemple Inc. Ltd", "groupe exemple"),
        ("Québec Numerique", "quebec numerique"),
        ("Lévesque & Cloutier Avocats", "levesque and cloutier avocats"),
        ("Lévesque et Cloutier Avocats", "levesque and cloutier avocats"),
        ("Groupe St-Pierre", "groupe st pierre"),
        ("Groupe St Pierre", "groupe st pierre"),
        ("Acme Technologies s.e.n.c.", "acme technologies"),
        ("Acme Technologies senc", "acme technologies"),
        ("Foo Coopérative", "foo"),
        ("Transport Gosselin enr.", "transport gosselin"),
    ],
)
def test_normalize_organization_name(raw, expected):
    assert normalize_organization_name(raw) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Groupe Exemple ltée", "Groupe Exemple Inc."),
        ("Groupe Exemple ltée", "GROUPE EXEMPLE"),
        ("Groupe Exemple limitée", "Groupe Exemple ltee"),
        ("Lévesque & Cloutier Avocats", "Lévesque et Cloutier Avocats"),
        ("Groupe St-Pierre", "Groupe St Pierre"),
        ("Coopérative de Rimouski", "Cooperative de Rimouski"),
        ("TRANSPORT GOSSELIN INC.", "Transport Gosselin"),
    ],
)
def test_organization_variants_share_a_key(left, right):
    """Synthetic-style duplicate changes should collapse to one comparison key."""
    assert normalize_organization_name(left) == normalize_organization_name(right)
    assert normalize_organization_name(left) is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("Marie-Ève Tremblay", "marie eve tremblay"),
        ("Marie Eve Tremblay", "marie eve tremblay"),
        ("MARIE-EVE TREMBLAY", "marie eve tremblay"),
        ("Émilie Gosselin", "emilie gosselin"),
        ("Jean-Philippe  St-Pierre", "jean philippe st pierre"),
    ],
)
def test_normalize_person_name(raw, expected):
    assert normalize_person_name(raw) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Marie-Ève Tremblay", "Marie Eve Tremblay"),
        ("Émilie Gosselin", "Emilie Gosselin"),
        ("Jean-Philippe St-Pierre", "Jean Philippe St Pierre"),
    ],
)
def test_person_variants_share_a_key(left, right):
    assert normalize_person_name(left) == normalize_person_name(right)
    assert normalize_person_name(left) is not None


@pytest.mark.parametrize(
    ("function", "args"),
    [
        (normalize_domain, (None,)),
        (normalize_domain, ("https://www.exemple.qc.ca",)),
        (normalize_linkedin, (None,)),
        (normalize_email, (None,)),
        (email_domain, (None,)),
    ],
)
def test_remaining_normalizer_stubs_return_none(function, args):
    assert function(*args) is None


def test_phone_stub_returns_empty_result():
    result = normalize_phone("+1 418 555 0100")

    assert isinstance(result, PhoneResult)
    assert result.e164 is None
    assert result.warnings == ()
