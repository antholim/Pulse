import json

import pytest
from pydantic import ValidationError

from synthetic.omerlo_schema import MODELS, Category, Content, write_json_schemas


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        Category.model_validate({"id": "1", "name": "Culture", "slug": "culture", "colour": "red"})


def test_profiles_block_links_organizations_and_people():
    content = Content.model_validate(
        {
            "id": "c1",
            "template_id": "article",
            "title_text": "Titre",
            "lead_text": None,
            "subtitle_text": None,
            "canonical_url": "https://example.test/c1",
            "visibility": "public",
            "is_advertising": False,
            "is_sponsored": True,
            "published_at": "2026-09-01T00:00:00Z",
            "author_ids": [],
            "category_ids": [],
            "visual": None,
            "blocks": [{"kind": "profiles", "profiles": [{"kind": "organization", "id": "o1"}]}],
            "updated_at": "2026-09-01T00:00:00Z",
        }
    )

    assert content.blocks[0].profiles[0].id == "o1"


def test_json_schemas_are_written_for_every_resource(tmp_path):
    paths = write_json_schemas(tmp_path)

    assert {p.name for p in paths} == {f"{name}.schema.json" for name in MODELS}
    organization = json.loads((tmp_path / "organizations.schema.json").read_text())
    assert "canonical_domain" in organization["properties"]
    assert organization["additionalProperties"] is False
