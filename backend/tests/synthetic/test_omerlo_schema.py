import json

import pytest
from pydantic import ValidationError

from synthetic.omerlo_schema import (
    MODELS,
    SUMMARY_MODELS,
    Contact,
    EventSummary,
    OrganizationSummary,
    summarize,
    write_json_schemas,
)

PROFILE = {
    "id": "e1",
    "workspace_id": "w1",
    "profile_categories": [{"id": "pc1", "category_id": "c1"}],
    "profile_type_id": "t1",
    "status_id": "s1",
    "canonical_url": "https://example.test/e1",
}


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        Contact.model_validate(
            {"id": "1", "locale": "fr", **dict.fromkeys(Contact.model_fields), "fax": "555"}
        )


def test_summary_keeps_only_the_list_fields():
    record = {
        "id": "o1",
        "name": "Groupe Exemple",
        "profile_image_key": None,
        "cover_image_key": None,
        "profile": PROFILE,
        "contact": [],
        "inserted_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
    }

    summary = summarize("organizations", record)

    OrganizationSummary.model_validate(summary)
    assert "contact" not in summary
    assert "workspace_id" not in summary["profile"]


def test_event_summary_carries_the_description_html_per_locale():
    block = {"kind": "richtext", "content_text": "Gala", "image": None}
    record = {
        "id": "e1",
        "profile": PROFILE,
        "profile_image_key": None,
        "description": [
            {"locale": "fr", "blocks": [{**block, "content_html": "<p>Gala</p>"}]},
            {"locale": "en", "blocks": [{**block, "content_html": None}]},
        ],
        "locales": [
            {"id": "l1", "locale": "fr", "name": "Gala", "summary_html": None, "deleted_at": None},
            {"id": "l2", "locale": "en", "name": "Gala", "summary_html": None, "deleted_at": None},
        ],
        "inserted_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
    }

    summary = EventSummary.model_validate(summarize("events", record))

    assert [locale.description_html for locale in summary.locales] == ["<p>Gala</p>", None]


def test_kinds_without_a_summary_are_listed_in_full():
    category = {"id": "c1", "locales": []}

    assert summarize("categories", category) is category


def test_json_schemas_are_written_for_every_resource_and_summary(tmp_path):
    paths = write_json_schemas(tmp_path)

    names = {p.name for p in paths}
    assert {f"{name}.schema.json" for name in MODELS} <= names
    assert {f"{name}.summary.schema.json" for name in SUMMARY_MODELS} <= names
    organization = json.loads((tmp_path / "organizations.schema.json").read_text())
    assert "contact" in organization["properties"]
    assert organization["additionalProperties"] is False
