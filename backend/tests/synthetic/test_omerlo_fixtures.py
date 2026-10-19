import json

import pytest

from synthetic.omerlo_fixtures import (
    NOTICE,
    TENANTS,
    OmerloFixtureGenerator,
    Sizes,
    main,
    write_fixtures,
)
from synthetic.omerlo_schema import MODELS

SEED = 490


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixtures")
    write_fixtures(OmerloFixtureGenerator(SEED).generate(), out, SEED)
    return out


def load(out_dir, media_id, kind):
    return json.loads((out_dir / media_id / f"{kind}.json").read_text(encoding="utf-8"))


def all_files(directory):
    return {p.relative_to(directory): p.read_bytes() for p in sorted(directory.rglob("*.json"))}


def test_same_seed_gives_byte_identical_files(out_dir, tmp_path):
    write_fixtures(OmerloFixtureGenerator(SEED).generate(), tmp_path, SEED)

    assert all_files(tmp_path) == all_files(out_dir)


def test_different_seed_gives_different_data(out_dir, tmp_path):
    write_fixtures(OmerloFixtureGenerator(SEED + 1).generate(), tmp_path, SEED + 1)

    first = load(out_dir, "demo-capitale", "organizations")
    other = json.loads((tmp_path / "demo-capitale" / "organizations.json").read_text())
    assert first != other


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.media_id)
@pytest.mark.parametrize("kind", list(MODELS))
def test_every_record_matches_the_omerlo_schema(out_dir, tenant, kind):
    model = MODELS[kind]
    for record in load(out_dir, tenant.media_id, kind):
        model.model_validate(record)


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.media_id)
def test_counts_match_the_requested_sizes(out_dir, tenant):
    sizes = Sizes()
    counts = {kind: len(load(out_dir, tenant.media_id, kind)) for kind in MODELS}

    assert counts["people"] == sizes.people
    assert counts["contents"] == sizes.contents
    assert counts["events"] == sizes.events
    assert counts["projects"] == sizes.projects
    assert counts["organizations"] >= sizes.organizations


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.media_id)
def test_ids_are_unique_within_a_tenant(out_dir, tenant):
    ids = [r["id"] for kind in MODELS for r in load(out_dir, tenant.media_id, kind)]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.media_id)
def test_about_ten_percent_of_contents_are_paid(out_dir, tenant):
    contents = load(out_dir, tenant.media_id, "contents")
    paid = [c for c in contents if c["is_sponsored"] or c["is_advertising"]]

    assert 0.07 <= len(paid) / len(contents) <= 0.13
    assert not any(c["is_sponsored"] and c["is_advertising"] for c in contents)


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.media_id)
def test_links_point_to_records_of_the_same_tenant(out_dir, tenant):
    media_id = tenant.media_id
    org_ids = {o["id"] for o in load(out_dir, media_id, "organizations")}
    person_ids = {p["id"] for p in load(out_dir, media_id, "people")}
    event_ids = {e["id"] for e in load(out_dir, media_id, "events")}
    contents = load(out_dir, media_id, "contents")

    linked = [
        ref
        for c in contents
        for block in c["blocks"]
        if block["kind"] == "profiles"
        for ref in block["profiles"]
    ]
    assert linked, "some contents should carry a Profiles block"
    for ref in linked:
        assert ref["id"] in (org_ids if ref["kind"] == "organization" else person_ids)
    for c in contents:
        if c["is_sponsored"] or c["is_advertising"]:
            assert any(b["kind"] == "profiles" for b in c["blocks"])

    participants = load(out_dir, media_id, "participants")
    assert set(participants) == event_ids
    assert all(p in person_ids for people in participants.values() for p in people)
    for event in load(out_dir, media_id, "events"):
        assert set(event["organizer_ids"]) <= org_ids


def test_some_organizations_exist_in_both_tenants_under_different_ids(out_dir):
    first, second = (load(out_dir, t.media_id, "organizations") for t in TENANTS)
    shared = {o["name"] for o in first} & {o["name"] for o in second}

    assert len(shared) >= Sizes().organizations * 0.2
    assert not {o["id"] for o in first} & {o["id"] for o in second}


def test_some_organizations_carry_a_crm_id(out_dir):
    organizations = load(out_dir, "demo-capitale", "organizations")

    assert any(m["key"] == "crm_id" for o in organizations for m in o["metadata"])


def test_manifest_marks_the_data_as_synthetic(out_dir):
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["synthetic"] is True
    assert manifest["notice"] == NOTICE
    assert manifest["seed"] == SEED
    assert [t["media_id"] for t in manifest["tenants"]] == [t.media_id for t in TENANTS]


def test_cli_writes_fixtures_and_schemas(tmp_path):
    main(["--seed", "7", "--out", str(tmp_path / "out"), "--schemas", str(tmp_path / "schemas")])

    assert (tmp_path / "out" / "manifest.json").exists()
    assert (tmp_path / "schemas" / "organizations.schema.json").exists()
