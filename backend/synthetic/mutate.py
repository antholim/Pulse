"""Apply a named set of adds, edits and deletes to synthetic Omerlo fixtures.

    uv run python -m synthetic.mutate --set demo           # fixtures in synthetic/out
    uv run python -m synthetic.mutate --set demo --fixtures /tmp/omerlo
    uv run python -m synthetic.mutate --reset              # back to the generated files
    uv run python -m synthetic.mutate --list

Changed records get an `updated_at` later than every record already in the
fixtures, so an incremental sync sees them. Each set writes
`expected_diff.<set>.json` next to the fixtures. The first set applied keeps a
copy of the original files in `.original/`, which `--reset` restores.
"""

import argparse
import copy
import random
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from synthetic import vocabulary as vocab
from synthetic.fixture_loader import load_fixtures, read_json
from synthetic.omerlo_fixtures import (
    GROUND_TRUTH_FILE,
    REFERENCE,
    Context,
    OmerloFixtureGenerator,
    OrgEntity,
    TenantData,
    domain_of,
    dump,
    fold,
    iso,
    slugify,
)
from synthetic.omerlo_schema import METADATA_FILE, MODELS, MetadataEntry

BACKUP_DIR = ".original"
MANIFEST = "manifest.json"
DEFAULT_FIXTURES = Path(__file__).parent / "out"


class MutationError(Exception):
    """The mutation set cannot be applied to these fixtures."""


# --------------------------------------------------------------------- format


@dataclass(frozen=True)
class Add:
    """New records; `kind` is organizations or people."""

    kind: str
    count: int = 1


@dataclass(frozen=True)
class Edit:
    """Change `fields` on `count` records; see EDITS for the fields of each kind."""

    kind: str
    fields: tuple[str, ...]
    count: int = 1


@dataclass(frozen=True)
class Delete:
    """Remove records; an event goes with its sessions."""

    kind: str
    count: int = 1


Step = Add | Edit | Delete


@dataclass(frozen=True)
class MutationSet:
    name: str
    description: str
    steps: tuple[Step, ...]
    seed: int = 0


DEMO = MutationSet(
    name="demo",
    description=(
        "Second sync of the demo: new organizations and people, edits to names and "
        "identifiers used for matching, and deleted records."
    ),
    steps=(
        Add("organizations", 2),
        Add("people", 3),
        Edit("organizations", ("name",)),
        Edit("organizations", ("domain",)),
        Edit("organizations", ("linkedin",)),
        Edit("organizations", ("crm_id",)),
        Edit("organizations", ("phone",)),
        Edit("organizations", ("name", "domain", "linkedin", "crm_id")),
        Edit("people", ("job_title",)),
        Edit("people", ("last_name", "email")),
        Edit("people", ("linkedin",)),
        Delete("organizations"),
        Delete("people", 2),
        Delete("events"),
    ),
)

MUTATION_SETS = {s.name: s for s in (DEMO,)}


# -------------------------------------------------------------------- helpers


def contact_values(record: dict[str, Any], name: str) -> set[str]:
    return {c[name] for c in record["contact"] if c[name]}


def base_name(name: str) -> str:
    """The organization name without its legal suffix."""
    for suffix in sorted(filter(None, vocab.LEGAL_SUFFIXES), key=len, reverse=True):
        if name.lower().endswith(f" {suffix.lower()}"):
            return name[: -len(suffix) - 1]
    return name


def person_slug(record: dict[str, Any]) -> str:
    return slugify(f"{record['first_name']} {record['last_name']}")


def label(record: dict[str, Any]) -> str:
    """A readable name for the record, for the expected diff."""
    if "name" in record:
        return record["name"]
    if "last_name" in record:
        return f"{record['first_name']} {record['last_name']}"
    locale = (record.get("locales") or [{}])[0]
    return locale.get("name") or locale.get("title_html") or record["id"]


class Clock:
    """Hands out `updated_at` values, one minute apart, after `start`."""

    def __init__(self, start: datetime):
        self.start = start
        self.ticks = 0

    def next(self) -> str:
        self.ticks += 1
        return iso(self.start + timedelta(minutes=self.ticks))


@dataclass
class Shared:
    """State shared by the tenants of one run."""

    clock: Clock
    # Organization keys identify one organization across tenants, so new ones never reuse a key.
    next_org_key: int


# ------------------------------------------------------------------- mutator


@dataclass
class TenantMutator:
    data: TenantData
    shared: Shared
    rng: random.Random
    touched: set[str] = field(default_factory=set)

    def __post_init__(self):
        self.gen = OmerloFixtureGenerator()
        self.gen.rng = self.rng
        self.res = self.data.resources

    def apply(self, steps: tuple[Step, ...]) -> None:
        for step in steps:
            if isinstance(step, Add):
                for _ in range(step.count):
                    self.add(step.kind)
            elif isinstance(step, Edit):
                self.edit(step)
            else:
                self.delete(step)

    # ---------------------------------------------------------------- picking

    def pick(self, kind: str, count: int, eligible: Callable[[dict], bool]) -> list[dict]:
        """`count` records chosen by the seeded RNG among untouched, eligible ones."""
        pool = sorted(
            (r for r in self.res[kind] if r["id"] not in self.touched and eligible(r)),
            key=lambda r: r["id"],
        )
        if len(pool) < count:
            raise MutationError(f"{self.data.tenant.slug}: not enough {kind} to change")
        chosen = self.rng.sample(pool, count)
        self.touched.update(r["id"] for r in chosen)
        return chosen

    def crm_id(self, record: dict[str, Any]) -> str | None:
        entries = self.data.metadata.get(record["id"], [])
        return next((e["value"] for e in entries if e["key"] == "crm_id"), None)

    def paired(self) -> set[str]:
        """Records in a deliberate duplicate pair; never deleted, so pairs stay whole."""
        truth = self.data.ground_truth
        pairs = truth.get("organization_duplicates", []) + truth.get("person_duplicates", [])
        return {record_id for pair in pairs for record_id in pair["record_ids"]}

    # ----------------------------------------------------------------- adding

    def context(self) -> Context:
        orgs = sorted(self.res["organizations"], key=lambda r: r["id"])
        types = [r["profile"]["profile_type_id"] for r in orgs]
        company = next((t for r, t in zip(orgs, types, strict=True) if self.crm_id(r)), types[0])
        organisme = next((t for t in types if t != company), company)
        person = min(r["profile"]["profile_type_id"] for r in self.res["people"])
        return Context(
            tenant=self.data.tenant,
            workspaces=self.res["workspaces"],
            categories=self.res["categories"],
            profile_types={"company": company, "organisme": organisme, "person": person},
        )

    def new_entity(self) -> OrgEntity:
        taken = {fold(r["name"]).lower() for r in self.res["organizations"]}
        while True:
            entity = self.gen.org_entities(1)[0]
            if fold(self.gen.org_name(entity)).lower() not in taken:
                return entity

    def add(self, kind: str) -> None:
        ctx = self.context()
        truth = self.data.ground_truth
        if kind == "organizations":
            entity = self.new_entity()
            record, metadata = self.gen.organization(entity, self.gen.org_name(entity), ctx)
            if metadata:
                self.data.metadata[record["id"]] = metadata
            if truth:
                truth["organizations"][record["id"]] = self.shared.next_org_key
            self.shared.next_org_key += 1
        elif kind == "people":
            employers = sorted(self.res["organizations"], key=lambda r: r["id"])
            record = self.gen.person(ctx, self.rng.choice(employers), journalist=False)
            if truth:
                truth["people"][record["id"]] = max(truth["people"].values(), default=-1) + 1
        else:
            raise MutationError(f"cannot add {kind}")
        record["inserted_at"] = record["updated_at"] = self.shared.clock.next()
        self.res[kind].append(record)
        self.touched.add(record["id"])

    # ---------------------------------------------------------------- editing

    def edit(self, step: Edit) -> None:
        editors = EDITS.get(step.kind, {})
        unknown = [f for f in step.fields if f not in editors]
        if unknown:
            raise MutationError(f"cannot edit {step.kind} {', '.join(unknown)}")
        needs = [editors[f][0] for f in step.fields]
        for record in self.pick(step.kind, step.count, lambda r: all(n(self, r) for n in needs)):
            for name in step.fields:
                editors[name][1](self, record)
            record["updated_at"] = self.shared.clock.next()

    def rename_organization(self, record: dict[str, Any]) -> None:
        record["name"] = self.gen.org_name(self.new_entity())

    def move_domain(self, record: dict[str, Any]) -> None:
        old = domain_of(record["profile"]["canonical_url"])
        slug = slugify(base_name(record["name"]))
        options = [slug + tld for tld in vocab.TOP_LEVEL_DOMAINS]
        domain = self.rng.choice([d for d in options if d != old])
        record["profile"]["canonical_url"] = f"https://www.{domain}"
        for contact in record["contact"]:
            if contact["website"]:
                english = contact["website"].endswith("/en")
                contact["website"] = f"https://www.{domain}" + ("/en" if english else "")
            if contact["email"]:
                contact["email"] = f"{contact['email'].split('@')[0]}@{domain}"

    def set_linkedin(self, record: dict[str, Any], path: str, slug: str) -> None:
        url = f"https://www.linkedin.com/{path}/{slug}"
        if url in contact_values(record, "linkedin"):
            url += f"-{self.rng.randint(2, 99)}"
        for contact in record["contact"]:
            contact["linkedin"] = url

    def change_org_linkedin(self, record: dict[str, Any]) -> None:
        self.set_linkedin(record, "company", slugify(base_name(record["name"])))

    def change_crm_id(self, record: dict[str, Any]) -> None:
        used = {e["value"] for entries in self.data.metadata.values() for e in entries}
        value = self.crm_id(record)
        while value in used:
            value = f"CRM-{self.rng.randint(10000, 99999)}"
        for entry in self.data.metadata[record["id"]]:
            if entry["key"] == "crm_id":
                entry["value"] = value

    def change_phone(self, record: dict[str, Any]) -> None:
        phone = self.gen.phone()
        for contact in record["contact"]:
            contact["phone"] = phone

    def change_last_name(self, record: dict[str, Any]) -> None:
        record["last_name"] = self.rng.choice(
            [n for n in vocab.LAST_NAMES if n != record["last_name"]]
        )

    def change_job_title(self, record: dict[str, Any]) -> None:
        current = record["locales"][0]["job_title"]
        title = self.rng.choice([t for t in vocab.JOB_TITLES if t not in (current, "Journaliste")])
        for locale in record["locales"]:
            locale["job_title"] = title

    def change_email(self, record: dict[str, Any]) -> None:
        old = next(iter(sorted(contact_values(record, "email"))))
        email = f"{person_slug(record).replace('-', '.')}@{old.split('@')[1]}"
        if email == old:
            # Same name: the person moved to another employer's domain.
            domains = sorted(
                {domain_of(r["profile"]["canonical_url"]) for r in self.res["organizations"]}
                - {None, old.split("@")[1]}
            )
            email = f"{old.split('@')[0]}@{self.rng.choice(domains)}"
        for contact in record["contact"]:
            contact["email"] = email

    def change_person_linkedin(self, record: dict[str, Any]) -> None:
        self.set_linkedin(record, "in", person_slug(record))

    # --------------------------------------------------------------- deleting

    def delete(self, step: Delete) -> None:
        paired = self.paired()
        owners = {p["owner_id"] for p in self.res["projects"]}
        sessions = self.res["event_sessions"]
        speakers = {s["actor_id"] for session in sessions for s in session["session_speakers"]}
        # Records still referenced by another record are not deleted.
        rules = {
            "organizations": lambda r: r["id"] not in paired | owners,
            "people": lambda r: r["id"] not in paired | speakers,
            "events": lambda r: True,
        }
        if step.kind not in rules:
            raise MutationError(f"cannot delete {step.kind}")
        gone = {r["id"] for r in self.pick(step.kind, step.count, rules[step.kind])}
        self.res[step.kind] = [r for r in self.res[step.kind] if r["id"] not in gone]
        if step.kind == "events":
            self.res["event_sessions"] = [
                s for s in self.res["event_sessions"] if s["event_id"] not in gone
            ]
        for record_id in gone:
            self.data.metadata.pop(record_id, None)
            for name in ("organizations", "people"):
                self.data.ground_truth.get(name, {}).pop(record_id, None)


def has_website(_: TenantMutator, record: dict[str, Any]) -> bool:
    return bool(record["profile"]["canonical_url"])


def has_contact(name: str) -> Callable[[TenantMutator, dict[str, Any]], bool]:
    return lambda _, record: bool(contact_values(record, name))


def always(_: TenantMutator, __: dict[str, Any]) -> bool:
    return True


# Field name -> (which records it applies to, how to change it).
EDITS: dict[str, dict[str, tuple[Callable, Callable]]] = {
    "organizations": {
        "name": (always, TenantMutator.rename_organization),
        "domain": (has_website, TenantMutator.move_domain),
        "linkedin": (has_contact("linkedin"), TenantMutator.change_org_linkedin),
        "crm_id": (lambda m, r: bool(m.crm_id(r)), TenantMutator.change_crm_id),
        "phone": (has_contact("phone"), TenantMutator.change_phone),
    },
    "people": {
        "last_name": (always, TenantMutator.change_last_name),
        # Journalists work for the media itself; their title stays.
        "job_title": (
            lambda _, r: bool(r["locales"]) and r["locales"][0]["job_title"] != "Journaliste",
            TenantMutator.change_job_title,
        ),
        "email": (has_contact("email"), TenantMutator.change_email),
        "linkedin": (has_contact("linkedin"), TenantMutator.change_person_linkedin),
    },
}


# ---------------------------------------------------------------------- diff


def value_changes(before: Any, after: Any, path: str) -> list[dict[str, Any]]:
    """Leaf changes between two values; per-locale lists are keyed by locale."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [
            change
            for key in sorted(before.keys() | after.keys())
            for change in value_changes(before.get(key), after.get(key), f"{path}.{key}")
        ]
    if by_locale(before) is not None and by_locale(after) is not None:
        old, new = by_locale(before), by_locale(after)
        return [
            change
            for locale in sorted(old.keys() | new.keys())
            for change in value_changes(old.get(locale), new.get(locale), f"{path}[{locale}]")
        ]
    return [{"field": path, "before": before, "after": after}]


def by_locale(value: Any) -> dict[str, Any] | None:
    if not (isinstance(value, list) and all(isinstance(v, dict) and "locale" in v for v in value)):
        return None
    keyed = {v["locale"]: v for v in value}
    return keyed if len(keyed) == len(value) else None


def record_changes(
    before: dict[str, Any], after: dict[str, Any], meta_before: list, meta_after: list
) -> list[dict[str, Any]]:
    changes = [
        change
        for key in sorted(before.keys() | after.keys())
        if key != "updated_at"
        for change in value_changes(before.get(key), after.get(key), key)
    ]
    old = {e["key"]: e["value"] for e in meta_before}
    new = {e["key"]: e["value"] for e in meta_after}
    changes += value_changes(old, new, METADATA_FILE) if old != new else []
    return changes


def tenant_diff(before: TenantData, after: TenantData) -> dict[str, list]:
    added, modified, removed = [], [], []
    for kind in MODELS:
        old = {r["id"]: r for r in before.resources[kind]}
        new = {r["id"]: r for r in after.resources[kind]}
        for record_id in sorted(new.keys() - old.keys()):
            record = new[record_id]
            added.append(
                {
                    "kind": kind,
                    "id": record_id,
                    "label": label(record),
                    "updated_at": record["updated_at"],
                }
            )
        for record_id in sorted(old.keys() & new.keys()):
            changes = record_changes(
                old[record_id],
                new[record_id],
                before.metadata.get(record_id, []),
                after.metadata.get(record_id, []),
            )
            if changes:
                modified.append(
                    {
                        "kind": kind,
                        "id": record_id,
                        "label": label(old[record_id]),
                        "updated_at": new[record_id]["updated_at"],
                        "fields": sorted({c["field"].split(".")[0].split("[")[0] for c in changes}),
                        "changes": changes,
                    }
                )
        removed += [
            {"kind": kind, "id": i, "label": label(old[i])} for i in sorted(old.keys() - new.keys())
        ]
    return {"added": added, "modified": modified, "removed": removed}


# ------------------------------------------------------------------ apply


def latest_update(tenants: list[TenantData]) -> datetime:
    stamps = [r["updated_at"] for t in tenants for records in t.resources.values() for r in records]
    latest = max([iso(REFERENCE), *stamps])
    return datetime.strptime(latest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def validate(data: TenantData, ids: set[str]) -> None:
    """Changed records must still match the backoffice schema."""
    for kind, model in MODELS.items():
        for record in data.resources[kind]:
            if record["id"] in ids:
                model.model_validate(record)
    for record_id in ids:
        for entry in data.metadata.get(record_id, []):
            MetadataEntry.model_validate(entry)


def mutate(
    tenants: list[TenantData], mutation_set: MutationSet
) -> tuple[list[TenantData], dict[str, Any]]:
    """The mutated tenants (the input is left as is) and the expected diff."""
    after = copy.deepcopy(tenants)
    latest = latest_update(tenants)
    org_keys = [k for t in tenants for k in t.ground_truth.get("organizations", {}).values()]
    shared = Shared(Clock(latest + timedelta(days=1)), max(org_keys, default=-1) + 1)
    diff: dict[str, Any] = {
        "synthetic": True,
        "mutation_set": mutation_set.name,
        "description": mutation_set.description,
        "changed_after": iso(latest),
        "tenants": {},
    }
    for before, data in zip(tenants, after, strict=True):
        rng = random.Random(f"{mutation_set.name}:{mutation_set.seed}:{data.tenant.slug}")
        mutator = TenantMutator(data, shared, rng)
        mutator.apply(mutation_set.steps)
        validate(data, mutator.touched)
        diff["tenants"][data.tenant.slug] = tenant_diff(before, data)
    return after, diff


def diff_path(fixtures: Path, name: str) -> Path:
    return fixtures / f"expected_diff.{name}.json"


def load_with_ground_truth(fixtures: Path) -> list[TenantData]:
    tenants = load_fixtures(fixtures)
    for data in tenants:
        path = fixtures / data.tenant.slug / GROUND_TRUTH_FILE
        if path.exists():
            data.ground_truth = read_json(path)
    return tenants


def apply_set(fixtures: Path, mutation_set: MutationSet) -> dict[str, Any]:
    """Mutate the fixture files in place and write the expected diff; returns the diff."""
    manifest = read_json(fixtures / MANIFEST)
    if mutation_set.name in manifest.get("mutations", []):
        raise MutationError(f"{mutation_set.name} is already applied; reset first")
    tenants, diff = mutate(load_with_ground_truth(fixtures), mutation_set)
    backup(fixtures)
    for data in tenants:
        tenant_dir = fixtures / data.tenant.slug
        for kind, records in data.resources.items():
            (tenant_dir / f"{kind}.json").write_text(dump(records), encoding="utf-8")
        (tenant_dir / f"{METADATA_FILE}.json").write_text(dump(data.metadata), encoding="utf-8")
        if data.ground_truth:
            (tenant_dir / GROUND_TRUTH_FILE).write_text(dump(data.ground_truth), encoding="utf-8")
    diff_path(fixtures, mutation_set.name).write_text(dump(diff), encoding="utf-8")
    counts = {t.tenant.slug: {k: len(v) for k, v in t.resources.items()} for t in tenants}
    for entry in manifest["tenants"]:
        entry["counts"] = counts[entry["slug"]]
    manifest["mutations"] = [*manifest.get("mutations", []), mutation_set.name]
    # Written last: the mock server reloads when the manifest changes.
    (fixtures / MANIFEST).write_text(dump(manifest), encoding="utf-8")
    return diff


# ------------------------------------------------------------------ reset


def fixture_files(directory: Path) -> list[Path]:
    """Fixture files relative to `directory`, the manifest last."""
    files = [
        p.relative_to(directory)
        for p in sorted(directory.rglob("*.json"))
        if BACKUP_DIR not in p.relative_to(directory).parts
        and not p.name.startswith("expected_diff.")
    ]
    return sorted(files, key=lambda p: p == Path(MANIFEST))


def backup(fixtures: Path) -> None:
    """Keep the files as they are before the first mutation."""
    target = fixtures / BACKUP_DIR
    if target.exists():
        return
    for path in fixture_files(fixtures):
        (target / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixtures / path, target / path)


def reset(fixtures: Path) -> bool:
    """Restore the original files and drop expected diffs; False if nothing was mutated."""
    source = fixtures / BACKUP_DIR
    if not source.exists():
        return False
    for path in fixture_files(source):
        shutil.copyfile(source / path, fixtures / path)
    for path in fixtures.glob("expected_diff.*.json"):
        path.unlink()
    shutil.rmtree(source)
    return True


# -------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--set", choices=sorted(MUTATION_SETS), help="mutation set to apply")
    action.add_argument("--reset", action="store_true", help="restore the original fixtures")
    action.add_argument("--list", action="store_true", help="list the mutation sets")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    args = parser.parse_args(argv)

    if args.list:
        for mutation_set in MUTATION_SETS.values():
            print(f"{mutation_set.name}: {mutation_set.description}")
    elif args.reset:
        restored = reset(args.fixtures)
        print(f"Restored {args.fixtures}" if restored else f"{args.fixtures} was not mutated")
    else:
        try:
            diff = apply_set(args.fixtures, MUTATION_SETS[args.set])
        except MutationError as error:
            parser.exit(1, f"error: {error}\n")
        for slug, changes in diff["tenants"].items():
            counts = ", ".join(f"{len(v)} {k}" for k, v in changes.items())
            print(f"{slug}: {counts}")
        print(f"Expected diff in {diff_path(args.fixtures, args.set)}")


if __name__ == "__main__":
    main()
