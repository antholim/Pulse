"""Tests for identifier normalization (#26)."""

import pytest

from app.processing import normalization as norm
from app.processing.normalization import (
    CONNECTOR_ALIASES,
    CONNECTOR_TOKEN,
    DEFAULT_PHONE_REGION,
    LINKEDIN_HOSTS,
    MAX_IDENTIFIER_LENGTH,
    PHONE_WARNING_EMPTY,
    PHONE_WARNING_IMPOSSIBLE,
    PHONE_WARNING_UNPARSEABLE,
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
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("not-a-domain", None),
        ("user@exemple.qc.ca", None),
        ("exemple.qc.ca", "exemple.qc.ca"),
        ("https://www.boutique.exemple.qc.ca/a-propos", "exemple.qc.ca"),
        ("HTTPS://WWW.Exemple.QC.CA/path?q=1", "exemple.qc.ca"),
        ("www.acme.io", "acme.io"),
        ("https://forums.bbc.co.uk/news", "bbc.co.uk"),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_domain_extractor_never_fetches():
    assert norm._domain_extractor().suffix_list_urls == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("https://example.com/company/acme", None),
        ("example.com/company/acme", None),
        ("https://www.linkedin.com/company/acme-tech/", "company/acme-tech"),
        ("https://www.linkedin.com/company/acme-tech?utm=1", "company/acme-tech"),
        ("https://fr.linkedin.com/in/marie-eve-tremblay/", "in/marie-eve-tremblay"),
        ("https://ca.linkedin.com/in/Marie-Eve", "in/marie-eve"),
        ("linkedin.com/company/acme", "company/acme"),
        ("/fr/company/acme", "company/acme"),
        ("company/acme", "company/acme"),
        ("company/acme?trk=public", "company/acme"),
        ("company/acme#section", "company/acme"),
        ("/fr/company/acme?trk=1#x", "company/acme"),
        ("in/marie-eve", "in/marie-eve"),
        ("company/acme!bad", None),
        ("in/not a slug", None),
    ],
)
def test_normalize_linkedin(raw, expected):
    assert normalize_linkedin(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected_email", "expected_domain"),
    [
        (None, None, None),
        ("", None, None),
        ("not-an-email", None, None),
        ("a@b", None, None),
        ("info@exemple.qc.ca", "info@exemple.qc.ca", "exemple.qc.ca"),
        ("  Info@Exemple.QC.CA  ", "info@exemple.qc.ca", "exemple.qc.ca"),
        ("a b@exemple.qc.ca", None, None),
    ],
)
def test_normalize_email_and_domain(raw, expected_email, expected_domain):
    assert normalize_email(raw) == expected_email
    assert email_domain(raw) == expected_domain


@pytest.mark.parametrize(
    ("raw", "expected_e164"),
    [
        ("+1 418 555 0100", "+14185550100"),
        ("+1-418-555-0100", "+14185550100"),
        ("(418) 555-0100", "+14185550100"),
        ("4185550100", "+14185550100"),
        ("514-555-9999", "+15145559999"),
    ],
)
def test_normalize_phone_to_e164(raw, expected_e164):
    result = normalize_phone(raw)

    assert isinstance(result, PhoneResult)
    assert result.e164 == expected_e164
    assert result.warnings == ()


@pytest.mark.parametrize(
    ("raw", "warning"),
    [
        (None, PHONE_WARNING_EMPTY),
        ("", PHONE_WARNING_EMPTY),
        ("   ", PHONE_WARNING_EMPTY),
        ("not-a-phone", PHONE_WARNING_UNPARSEABLE),
        ("123", PHONE_WARNING_IMPOSSIBLE),
    ],
)
def test_normalize_phone_invalid_returns_warning(raw, warning):
    result = normalize_phone(raw)

    assert result.e164 is None
    assert warning in result.warnings


def test_normalize_phone_never_raises_on_garbage():
    result = normalize_phone("++not@@a##phone")

    assert result.e164 is None
    assert result.warnings


def test_oversized_inputs_are_rejected():
    oversized = "a" * (MAX_IDENTIFIER_LENGTH + 1)

    assert normalize_organization_name(oversized) is None
    assert normalize_person_name(oversized) is None
    assert normalize_domain(oversized) is None
    assert normalize_linkedin(f"company/{oversized}") is None
    assert normalize_email(f"{oversized}@exemple.qc.ca") is None

    phone = normalize_phone(oversized)
    assert phone.e164 is None
    assert PHONE_WARNING_UNPARSEABLE in phone.warnings
