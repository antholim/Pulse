import pytest

from synthetic.fixture_loader import read_json
from synthetic.mutate import (
    BACKUP_DIR,
    DEMO,
    Add,
    Delete,
    Edit,
    MutationError,
    MutationSet,
    apply_set,
    load_with_ground_truth,
    main,
    mutate,
    reset,
    value_changes,
)
from synthetic.omerlo_fixtures import GROUND_TRUTH_FILE, OmerloFixtureGenerator, write_fixtures
from synthetic.omerlo_schema import MODELS
from tests.synthetic.conftest import SMALL

SEED = 5


def all_files(directory):
    return {
        p.relative_to(directory): p.read_bytes()
        for p in sorted(directory.rglob("*.json"))
        if BACKUP_DIR not in p.parts
    }


@pytest.fixture
def fixtures(tmp_path):
    out = tmp_path / "fixtures"
    write_fixtures(OmerloFixtureGenerator(SEED, SMALL).generate(), out, SEED)
    return out


@pytest.fixture(scope="module")
def demo():
    """The demo set applied in memory: tenants before, tenants after, expected diff."""
    before = OmerloFixtureGenerator(SEED, SMALL).generate()
    after, diff = mutate(before, DEMO)
    return before, after, diff


def by_id(data, kind):
    return {r["id"]: r for r in data.resources[kind]}


# -------------------------------------------------------------- the changes


def test_demo_adds_edits_and_deletes_in_every_tenant(demo):
    # Arrange
    _, _, diff = demo

    # Act
    counts = {
        slug: {kind: len(entries) for kind, entries in changes.items()}
        for slug, changes in diff["tenants"].items()
    }

    # Assert
    for slug, count in counts.items():
        assert count["added"] == 5, slug
        assert count["modified"] == 9, slug
        # One organization, two people, one event and its sessions.
        assert count["removed"] >= 5, slug


def test_changed_records_are_newer_than_every_original_record(demo):
    # Arrange
    before, after, diff = demo
    latest = max(r["updated_at"] for t in before for rs in t.resources.values() for r in rs)

    # Act
    changed = [
        by_id(data, entry["kind"])[entry["id"]]
        for data in after
        for entry in diff["tenants"][data.tenant.slug]["added"]
        + diff["tenants"][data.tenant.slug]["modified"]
    ]

    # Assert
    assert diff["changed_after"] >= latest
    assert all(r["updated_at"] > diff["changed_after"] for r in changed)
    assert len({r["updated_at"] for r in changed}) == len(changed)


def test_unchanged_records_keep_their_updated_at(demo):
    # Arrange
    before, after, diff = demo

    # Act
    changed = {e["id"] for t in diff["tenants"].values() for e in t["added"] + t["modified"]}

    # Assert
    for old, new in zip(before, after, strict=True):
        for kind in MODELS:
            current = by_id(new, kind)
            for record in old.resources[kind]:
                if record["id"] in current and record["id"] not in changed:
                    assert current[record["id"]] == record


def test_edits_cover_single_and_multi_field_changes_on_matching_fields(demo):
    # Arrange
    before, _, diff = demo
    modified = diff["tenants"][before[0].tenant.slug]["modified"]

    # Act
    orgs = [m for m in modified if m["kind"] == "organizations"]
    org_fields = [{c["field"].split(".")[-1] for c in m["changes"]} for m in orgs]

    # Assert
    assert {"name"} in org_fields
    assert {"crm_id"} in org_fields
    assert {"linkedin"} in org_fields
    assert {"canonical_url", "website", "email"} in org_fields
    assert {"name", "canonical_url", "website", "email", "linkedin", "crm_id"} in org_fields


def test_expected_diff_matches_the_mutated_records(demo):
    # Arrange
    before, after, diff = demo
    old, new = before[0], after[0]
    changes = diff["tenants"][old.tenant.slug]

    # Act
    renamed = next(m for m in changes["modified"] if m["fields"] == ["name"])

    # Assert
    record = by_id(new, "organizations")[renamed["id"]]
    assert renamed["changes"] == [
        {
            "field": "name",
            "before": by_id(old, "organizations")[renamed["id"]]["name"],
            "after": record["name"],
        }
    ]
    assert renamed["updated_at"] == record["updated_at"]
    for entry in changes["added"]:
        assert entry["id"] in by_id(new, entry["kind"])
    for entry in changes["removed"]:
        assert entry["id"] in by_id(old, entry["kind"])
        assert entry["id"] not in by_id(new, entry["kind"])


def test_metadata_change_bumps_the_record(demo):
    # Arrange
    before, after, diff = demo
    old, new = before[0], after[0]

    # Act
    crm = next(
        m for m in diff["tenants"][old.tenant.slug]["modified"] if m["fields"] == ["metadata"]
    )

    # Assert
    assert crm["changes"][0]["field"] == "metadata.crm_id"
    assert new.metadata[crm["id"]] != old.metadata[crm["id"]]
    assert by_id(new, "organizations")[crm["id"]]["updated_at"] > diff["changed_after"]


def test_mutated_records_still_match_the_schema(demo):
    # Arrange
    _, after, _ = demo

    # Act
    records = [(kind, r) for data in after for kind in MODELS for r in data.resources[kind]]

    # Assert
    for kind, record in records:
        MODELS[kind].model_validate(record)


def test_deleted_event_takes_its_sessions_and_nothing_points_at_deleted_records(demo):
    # Arrange
    _, after, _ = demo

    # Act
    for data in after:
        events = by_id(data, "events")
        orgs = by_id(data, "organizations")
        people = by_id(data, "people")

        # Assert
        assert all(s["event_id"] in events for s in data.resources["event_sessions"])
        assert all(p["owner_id"] in orgs for p in data.resources["projects"])
        assert all(
            s["actor_id"] in people
            for session in data.resources["event_sessions"]
            for s in session["session_speakers"]
        )
        assert set(data.metadata) <= set(orgs) | set(people)


def test_ground_truth_follows_adds_and_deletes(demo):
    # Arrange
    before, after, _ = demo
    old_keys = {k for t in before for k in t.ground_truth["organizations"].values()}

    # Act
    added_keys = [
        key
        for old, new in zip(before, after, strict=True)
        for record_id, key in new.ground_truth["organizations"].items()
        if record_id not in old.ground_truth["organizations"]
    ]

    # Assert
    for data in after:
        assert set(data.ground_truth["organizations"]) == set(by_id(data, "organizations"))
        assert set(data.ground_truth["people"]) == set(by_id(data, "people"))
    # New organizations are new entities, in neither tenant before.
    assert len(added_keys) == len(set(added_keys)) == 4
    assert not set(added_keys) & old_keys


def test_mutate_leaves_its_input_untouched():
    # Arrange
    tenants = OmerloFixtureGenerator(SEED, SMALL).generate()
    copy = OmerloFixtureGenerator(SEED, SMALL).generate()

    # Act
    mutate(tenants, DEMO)

    # Assert
    assert [t.resources for t in tenants] == [t.resources for t in copy]


def test_unknown_or_impossible_steps_fail():
    # Arrange
    tenants = OmerloFixtureGenerator(SEED, SMALL).generate()
    bad_sets = [
        MutationSet("x", "", (Edit("organizations", ("color",)),)),
        MutationSet("x", "", (Add("events"),)),
        MutationSet("x", "", (Delete("workspaces"),)),
        MutationSet("x", "", (Delete("events", 1000),)),
    ]

    # Act and Assert
    for bad in bad_sets:
        with pytest.raises(MutationError):
            mutate(tenants, bad)


def test_value_changes_key_locale_lists_by_locale():
    # Arrange
    before = {"contact": [{"locale": "fr", "phone": "1"}]}
    after = {"contact": [{"locale": "fr", "phone": "2"}, {"locale": "en", "phone": "2"}]}

    # Act
    changes = value_changes(before, after, "record")

    # Assert
    assert changes == [
        {"field": "record.contact[en]", "before": None, "after": {"locale": "en", "phone": "2"}},
        {"field": "record.contact[fr].phone", "before": "1", "after": "2"},
    ]


# ------------------------------------------------------------- files, reset


def test_same_set_on_same_fixtures_gives_byte_identical_files(fixtures, tmp_path):
    # Arrange
    other = tmp_path / "other"
    write_fixtures(OmerloFixtureGenerator(SEED, SMALL).generate(), other, SEED)

    # Act
    apply_set(fixtures, DEMO)
    apply_set(other, DEMO)

    # Assert
    assert all_files(fixtures) == all_files(other)


def test_apply_writes_the_expected_diff_and_records_the_set(fixtures):
    # Act
    diff = apply_set(fixtures, DEMO)

    # Assert
    assert read_json(fixtures / "expected_diff.demo.json") == diff
    manifest = read_json(fixtures / "manifest.json")
    assert manifest["mutations"] == ["demo"]
    for data in load_with_ground_truth(fixtures):
        counts = next(t["counts"] for t in manifest["tenants"] if t["slug"] == data.tenant.slug)
        assert counts == {kind: len(records) for kind, records in data.resources.items()}
        written = read_json(fixtures / data.tenant.slug / GROUND_TRUTH_FILE)
        assert set(written["organizations"]) == {r["id"] for r in data.resources["organizations"]}


def test_a_set_cannot_be_applied_twice(fixtures):
    # Arrange
    apply_set(fixtures, DEMO)

    # Act and Assert
    with pytest.raises(MutationError, match="already applied"):
        apply_set(fixtures, DEMO)


def test_sets_stack_and_reset_restores_the_original_files(fixtures):
    # Arrange
    original = all_files(fixtures)
    second = MutationSet("second", "More edits.", (Edit("people", ("last_name",), 2),))

    # Act
    first_diff = apply_set(fixtures, DEMO)
    second_diff = apply_set(fixtures, second)
    restored = reset(fixtures)

    # Assert
    assert second_diff["changed_after"] > first_diff["changed_after"]
    assert restored
    assert all_files(fixtures) == original
    assert not (fixtures / BACKUP_DIR).exists()
    assert not reset(fixtures)


def test_cli_applies_lists_and_resets(fixtures, capsys):
    # Arrange
    original = all_files(fixtures)

    # Act
    main(["--list"])
    main(["--set", "demo", "--fixtures", str(fixtures)])
    mutated = all_files(fixtures)
    main(["--reset", "--fixtures", str(fixtures)])
    main(["--reset", "--fixtures", str(fixtures)])

    # Assert
    out = capsys.readouterr().out
    assert "demo:" in out
    assert "5 added" in out
    assert "was not mutated" in out
    assert mutated != original
    assert all_files(fixtures) == original


def test_cli_reports_a_set_applied_twice(fixtures):
    # Arrange
    main(["--set", "demo", "--fixtures", str(fixtures)])

    # Act and Assert
    with pytest.raises(SystemExit) as exit_info:
        main(["--set", "demo", "--fixtures", str(fixtures)])
    assert exit_info.value.code == 1
