import json

import pytest

from synthetic.omerlo_fixtures import (
    GROUND_TRUTH_FILE,
    NOTICE,
    TENANTS,
    OmerloFixtureGenerator,
    Sizes,
    domain_of,
    main,
    write_fixtures,
)
from synthetic.omerlo_schema import METADATA_FILE, MODELS, SUMMARY_MODELS, summarize

SEED = 490
PROFILE_KINDS = ("organizations", "people", "projects", "events")


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixtures")
    write_fixtures(OmerloFixtureGenerator(SEED).generate(), out, SEED)
    return out


def load(out_dir, slug, kind):
    return json.loads((out_dir / slug / f"{kind}.json").read_text(encoding="utf-8"))


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


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.slug)
@pytest.mark.parametrize("kind", list(MODELS))
def test_every_record_matches_the_backoffice_schema(out_dir, tenant, kind):
    for record in load(out_dir, tenant.slug, kind):
        MODELS[kind].model_validate(record)
        if kind in SUMMARY_MODELS:
            SUMMARY_MODELS[kind].model_validate(summarize(kind, record))


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.slug)
def test_counts_match_the_requested_sizes(out_dir, tenant):
    sizes = Sizes()
    counts = {kind: len(load(out_dir, tenant.slug, kind)) for kind in MODELS}

    assert counts["workspaces"] == len(tenant.workspaces)
    assert counts["people"] >= sizes.people
    assert counts["events"] == sizes.events
    assert counts["projects"] == sizes.projects
    assert counts["organizations"] >= sizes.organizations
    assert counts["event_sessions"] >= sizes.events


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.slug)
def test_ids_are_unique_within_a_tenant(out_dir, tenant):
    ids = [r["id"] for kind in MODELS for r in load(out_dir, tenant.slug, kind)]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.slug)
def test_contact_and_address_have_one_entry_per_locale(out_dir, tenant):
    organizations = load(out_dir, tenant.slug, "organizations")
    locale_sets = set()
    for org in organizations:
        locales = [entry["locale"] for entry in org["locales"]]
        assert [c["locale"] for c in org["contact"]] == locales
        assert [a["locale"] for a in org["address"]] == locales
        locale_sets.add(tuple(locales))

    assert ("fr", "en") in locale_sets
    assert any(len(locales) == 1 for locales in locale_sets)


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.slug)
def test_profiles_point_to_records_of_the_same_tenant(out_dir, tenant):
    slug = tenant.slug
    workspace_ids = {w["id"] for w in load(out_dir, slug, "workspaces")}
    category_ids = {c["id"] for c in load(out_dir, slug, "categories")}
    status_ids = {s["id"] for w in load(out_dir, slug, "workspaces") for s in w["statuses"]}

    for kind in PROFILE_KINDS:
        for record in load(out_dir, slug, kind):
            profile = record["profile"]
            assert profile["id"] == record["id"]
            assert profile["workspace_id"] in workspace_ids
            assert profile["status_id"] in status_ids
            assert {c["category_id"] for c in profile["profile_categories"]} <= category_ids


def test_records_are_spread_across_a_tenants_workspaces(out_dir):
    tenant = TENANTS[0]
    used = {o["profile"]["workspace_id"] for o in load(out_dir, tenant.slug, "organizations")}

    assert len(tenant.workspaces) > 1
    assert len(used) == len(tenant.workspaces)


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.slug)
def test_sessions_and_projects_link_to_records_of_the_same_tenant(out_dir, tenant):
    slug = tenant.slug
    event_ids = {e["id"] for e in load(out_dir, slug, "events")}
    person_ids = {p["id"] for p in load(out_dir, slug, "people")}
    org_ids = {o["id"] for o in load(out_dir, slug, "organizations")}
    sessions = load(out_dir, slug, "event_sessions")

    assert {s["event_id"] for s in sessions} == event_ids
    speakers = [sp["actor_id"] for s in sessions for sp in s["session_speakers"]]
    assert speakers
    assert set(speakers) <= person_ids
    assert {p["owner_id"] for p in load(out_dir, slug, "projects")} <= org_ids


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.slug)
def test_metadata_is_served_apart_from_the_records(out_dir, tenant):
    metadata = load(out_dir, tenant.slug, METADATA_FILE)
    org_ids = {o["id"] for o in load(out_dir, tenant.slug, "organizations")}

    assert metadata
    assert set(metadata) <= org_ids
    assert all(e["key"] == "crm_id" for entries in metadata.values() for e in entries)
    assert all("metadata" not in o for o in load(out_dir, tenant.slug, "organizations"))


def test_some_organizations_exist_in_both_tenants_under_different_ids(out_dir):
    first, second = (load(out_dir, t.slug, "organizations") for t in TENANTS)
    shared = {o["name"] for o in first} & {o["name"] for o in second}

    assert len(shared) >= Sizes().organizations * 0.2
    assert not {o["id"] for o in first} & {o["id"] for o in second}


def test_manifest_marks_the_data_as_synthetic(out_dir):
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["synthetic"] is True
    assert manifest["notice"] == NOTICE
    assert manifest["seed"] == SEED
    assert [t["slug"] for t in manifest["tenants"]] == [t.slug for t in TENANTS]


def test_cli_writes_fixtures_and_schemas(tmp_path):
    main(["--seed", "7", "--out", str(tmp_path / "out"), "--schemas", str(tmp_path / "schemas")])

    assert (tmp_path / "out" / "manifest.json").exists()
    assert (tmp_path / "schemas" / "organizations.schema.json").exists()
    assert (tmp_path / "schemas" / "organizations.summary.schema.json").exists()


def ground_truth(out_dir, slug):
    return json.loads((out_dir / slug / GROUND_TRUTH_FILE).read_text(encoding="utf-8"))


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.slug)
def test_ground_truth_is_marked_dev_only_and_covers_every_record(out_dir, tenant):
    truth = ground_truth(out_dir, tenant.slug)

    assert truth["dev_only"] is True
    assert "Never use it for the official" in truth["notice"]
    org_ids = {o["id"] for o in load(out_dir, tenant.slug, "organizations")}
    person_ids = {p["id"] for p in load(out_dir, tenant.slug, "people")}
    assert set(truth["organizations"]) == org_ids
    assert set(truth["people"]) == person_ids


@pytest.mark.parametrize("tenant", TENANTS, ids=lambda t: t.slug)
def test_duplicates_are_differently_spelled_records_of_one_entity(out_dir, tenant):
    truth = ground_truth(out_dir, tenant.slug)
    organizations = {o["id"]: o for o in load(out_dir, tenant.slug, "organizations")}
    clusters = truth["organization_duplicates"]

    assert len(clusters) >= Sizes().organizations * 0.1
    for cluster in clusters:
        original, duplicate = (organizations[i] for i in cluster["record_ids"])
        assert original["name"] != duplicate["name"]
        assert cluster["changes"]
        assert {truth["organizations"][i] for i in cluster["record_ids"]} == {cluster["entity"]}

    people = {p["id"]: p for p in load(out_dir, tenant.slug, "people")}
    assert truth["person_duplicates"]
    for cluster in truth["person_duplicates"]:
        original, duplicate = (people[i] for i in cluster["record_ids"])
        assert (original["first_name"], original["last_name"]) != (
            duplicate["first_name"],
            duplicate["last_name"],
        )


def test_duplicates_need_both_exact_and_fuzzy_matching(out_dir):
    """Some pairs share a strong identifier (Tier 1); others share none (Tier 2 only)."""
    organizations = {o["id"]: o for o in load(out_dir, "demo-capitale", "organizations")}
    metadata = load(out_dir, "demo-capitale", METADATA_FILE)

    def identifiers(org):
        crm = {m["value"] for m in metadata.get(org["id"], []) if m["key"] == "crm_id"}
        contact = {domain_of(c["website"]) for c in org["contact"]}
        contact |= {c["linkedin"] for c in org["contact"]}
        return (contact | crm) - {None}

    shared = [
        bool(identifiers(organizations[a]) & identifiers(organizations[b]))
        for a, b in (
            c["record_ids"]
            for c in ground_truth(out_dir, "demo-capitale")["organization_duplicates"]
        )
    ]
    assert any(shared)
    assert not all(shared)


def test_ground_truth_keys_identify_organizations_across_tenants(out_dir):
    first, second = (set(ground_truth(out_dir, t.slug)["organizations"].values()) for t in TENANTS)

    assert first & second
