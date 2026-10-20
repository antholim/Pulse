"""Seeded generator of synthetic Omerlo Reader API fixtures for two tenants.

    uv run python -m synthetic.omerlo_fixtures --seed 490 --out synthetic/out

Writes `<out>/<media id>/<kind>.json` for every resource in `omerlo_schema.MODELS`,
`participants.json` per tenant (event id to person ids), `manifest.json`, and a
dev-only `ground_truth.dev_only.json` per tenant listing the deliberate duplicates.
The same seed always produces byte-identical files. All data is invented.
"""

import argparse
import copy
import json
import random
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from synthetic import vocabulary as vocab
from synthetic.omerlo_schema import write_json_schemas

# Fixed "now", so output does not depend on when the generator runs.
REFERENCE = datetime(2026, 10, 1, tzinfo=UTC)
DEFAULT_SEED = 490
NOTICE = "SYNTHETIC DATA generated for PULSE development. No real person or organization."
GROUND_TRUTH_NOTICE = (
    "DEV ONLY. Ground truth of the synthetic duplicates, for checking matching during "
    "development. Never use it for the official entity resolution evaluation, which needs "
    "real sponsor-approved data."
)
GROUND_TRUTH_FILE = "ground_truth.dev_only.json"

# Ways another source may spell the same organization name, and how often each is picked.
NAME_CHANGES = ("suffix", "accents", "case", "hyphen", "ampersand")
NAME_CHANGE_WEIGHTS = (4, 3, 1, 2, 1)


@dataclass(frozen=True)
class Tenant:
    media_id: str
    name: str
    site: str


TENANTS = (
    Tenant("demo-capitale", "Média démo Capitale", "capitale.example"),
    Tenant("demo-estrie", "Média démo Estrie", "estrie.example"),
)


@dataclass(frozen=True)
class Sizes:
    organizations: int = 150
    people: int = 300
    contents: int = 1000
    events: int = 60
    projects: int = 20
    authors: int = 15
    # Share of each tenant's organizations that also exist in the other tenant.
    shared_share: float = 0.25
    # Share of organizations and people that get a second, differently spelled record.
    duplicate_org_share: float = 0.12
    duplicate_person_share: float = 0.04


@dataclass
class OrgEntity:
    """A fictional real-world organization; each tenant renders its own record of it."""

    key: int
    base_name: str
    suffix: str
    city: str
    region: str
    domain: str | None
    linkedin: str | None
    crm_id: str | None


@dataclass
class TenantData:
    tenant: Tenant
    resources: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    participants: dict[str, list[str]] = field(default_factory=dict)
    ground_truth: dict[str, Any] = field(default_factory=dict)


def fold(text: str) -> str:
    """Drop accents, keeping case: `Québec` becomes `Quebec`."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(text).lower()).strip("-")


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class OmerloFixtureGenerator:
    def __init__(self, seed: int = DEFAULT_SEED, sizes: Sizes | None = None):
        self.seed = seed
        self.sizes = sizes or Sizes()
        self.rng = random.Random(seed)

    # ----------------------------------------------------------------- helpers

    def new_id(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def moment(self, days_back: int = 365, days_forward: int = 0) -> datetime:
        seconds = self.rng.randint(-days_back * 86400, days_forward * 86400)
        return REFERENCE + timedelta(seconds=seconds)

    def phone(self) -> str:
        # 555 exchanges are reserved for fiction.
        return f"+1 418 555 {self.rng.randint(0, 9999):04d}"

    def postal_code(self, city: str) -> str:
        letters = "ABCEGHJKLMNPRSTVXY"
        r = self.rng
        first = f"{vocab.POSTAL_PREFIX[city]}{r.randint(0, 9)}{r.choice(letters)}"
        return f"{first} {r.randint(0, 9)}{r.choice(letters)}{r.randint(0, 9)}"

    def address(self, city: str) -> dict[str, Any]:
        return {
            "street": f"{self.rng.randint(1, 9999)} {self.rng.choice(vocab.STREETS)}",
            "location": self.postal_code(city),
            "city": city,
            "state": "QC",
            "country": "CA",
        }

    @staticmethod
    def contact(**values: str | None) -> dict[str, Any]:
        keys = ("email", "phone", "linkedin", "website", "facebook", "instagram", "twitter")
        return {**dict.fromkeys(keys), "bluesky": None, **values}

    # ---------------------------------------------------------------- entities

    def org_entities(self, count: int) -> list[OrgEntity]:
        entities, names = [], set()
        while len(entities) < count:
            surname, surname2 = self.rng.sample(vocab.LAST_NAMES, 2)
            city, region = self.rng.choice(vocab.CITIES)
            pattern = self.rng.choice(vocab.ORG_PATTERNS)
            base = pattern.format(s=surname, s2=surname2, c=city)
            institution = base.startswith(vocab.INSTITUTION_PREFIXES)
            if base in names:
                continue
            names.add(base)
            slug = slugify(base)
            entities.append(
                OrgEntity(
                    key=len(entities),
                    base_name=base,
                    suffix="" if institution else self.rng.choice(vocab.LEGAL_SUFFIXES),
                    city=city,
                    region=region,
                    domain=None
                    if self.rng.random() < 0.1
                    else slug + self.rng.choice(vocab.TOP_LEVEL_DOMAINS),
                    linkedin=f"https://www.linkedin.com/company/{slug}"
                    if self.rng.random() < 0.6
                    else None,
                    crm_id=f"CRM-{self.rng.randint(10000, 99999)}"
                    if self.rng.random() < 0.5
                    else None,
                )
            )
        return entities

    # --------------------------------------------------------------- resources

    def categories(self) -> list[dict[str, Any]]:
        return [{"id": self.new_id(), "name": n, "slug": s} for n, s in vocab.CATEGORIES]

    def profile_types(self) -> list[dict[str, Any]]:
        # The company type carries a CRM id, used as an external id for matching.
        types = [
            ("Entreprise", "organization", ["crm_id"]),
            ("Organisme", "organization", []),
            ("Personne", "person", []),
        ]
        return [
            {"id": self.new_id(), "name": name, "kind": kind, "metadata_keys": keys}
            for name, kind, keys in types
        ]

    def organization(
        self, entity: OrgEntity, name: str, profile_types: list, categories: list
    ) -> dict[str, Any]:
        company, organisme = profile_types[0], profile_types[1]
        profile_type = company if entity.crm_id else self.rng.choice([company, organisme])
        domain = entity.domain
        return {
            "id": self.new_id(),
            "profile_type_id": profile_type["id"],
            "name": name,
            "summary_text": f"{entity.base_name}, à {entity.city}.",
            "canonical_url": f"https://www.{domain}" if domain else None,
            "canonical_domain": domain,
            "address": self.address(entity.city),
            "description": {
                "blocks": [{"kind": "paragraph", "text": f"Présentation de {entity.base_name}."}]
            },
            "contact": self.contact(
                email=f"info@{domain}" if domain else None,
                phone=self.phone(),
                linkedin=entity.linkedin,
                website=f"https://www.{domain}" if domain else None,
            ),
            "category_ids": [c["id"] for c in self.rng.sample(categories, self.rng.randint(1, 2))],
            "metadata": [{"key": "crm_id", "value": entity.crm_id}]
            if entity.crm_id and profile_type is company
            else [],
            "meta": {"locales": self.rng.choice([["fr"], ["fr"], ["fr", "en"]])},
            "updated_at": iso(self.moment()),
        }

    def person(
        self, tenant: Tenant, organizations: list, profile_types: list, journalist: bool
    ) -> dict[str, Any]:
        first, last = self.rng.choice(vocab.FIRST_NAMES), self.rng.choice(vocab.LAST_NAMES)
        employer = self.rng.choice(organizations)
        domain = tenant.site if journalist else employer["canonical_domain"]
        city = employer["address"]["city"]
        slug = slugify(f"{first} {last}")
        return {
            "id": self.new_id(),
            "profile_type_id": profile_types[2]["id"],
            "first_name": first,
            "last_name": last,
            "other_name": None,
            "pronoun": self.rng.choice([None, None, "elle", "il", "iel"]),
            "job_title": "Journaliste" if journalist else self.rng.choice(vocab.JOB_TITLES),
            "canonical_url": f"https://{tenant.site}/personnes/{slug}",
            "address": self.address(city),
            "contact": self.contact(
                email=f"{slug.replace('-', '.')}@{domain}" if domain else None,
                linkedin=f"https://www.linkedin.com/in/{slug}" if self.rng.random() < 0.5 else None,
            ),
            "category_ids": [],
            "metadata": [],
            "updated_at": iso(self.moment()),
        }

    def content(
        self, tenant: Tenant, organizations: list, people: list, authors: list, categories: list
    ) -> dict[str, Any]:
        roll = self.rng.random()
        is_sponsored, is_advertising = roll < 0.06, 0.06 <= roll < 0.10
        org = self.rng.choice(organizations)
        person = self.rng.choice(people)
        city = org["address"]["city"]
        templates = vocab.SPONSORED_HEADLINES if is_sponsored or is_advertising else vocab.HEADLINES
        title = self.rng.choice(templates).format(
            org=org["name"], c=city, person=f"{person['first_name']} {person['last_name']}"
        )
        content_id = self.new_id()

        blocks = [{"kind": "paragraph", "text": f"{title}. Article fictif généré pour PULSE."}]
        if is_sponsored or is_advertising or self.rng.random() < 0.35:
            linked = [org, *self.rng.sample(organizations, self.rng.randint(0, 2))]
            org_ids = dict.fromkeys(o["id"] for o in linked)  # unique, in order
            refs = [{"kind": "organization", "id": i} for i in org_ids]
            refs += [
                {"kind": "person", "id": p["id"]}
                for p in self.rng.sample(people, self.rng.randint(0, 2))
            ]
            blocks.append({"kind": "profiles", "profiles": refs})

        published = self.moment()
        updated = min(published + timedelta(days=self.rng.randint(0, 30)), REFERENCE)
        return {
            "id": content_id,
            "template_id": "publicite"
            if is_advertising
            else "partenaire"
            if is_sponsored
            else self.rng.choice(["article", "article", "chronique"]),
            "title_text": title,
            "lead_text": f"À {city}, {org['name']} fait parler de lui.",
            "subtitle_text": None,
            "canonical_url": f"https://{tenant.site}/{slugify(title)[:60]}-{content_id[:8]}",
            "visibility": self.rng.choice(["public", "public", "subscribers"]),
            "is_advertising": is_advertising,
            "is_sponsored": is_sponsored,
            "published_at": iso(published),
            "author_ids": []
            if is_advertising
            else [a["id"] for a in self.rng.sample(authors, self.rng.randint(1, 2))],
            "category_ids": [c["id"] for c in self.rng.sample(categories, self.rng.randint(1, 2))],
            "visual": {"url": f"https://images.{tenant.site}/{content_id}.jpg", "caption": None}
            if self.rng.random() < 0.5
            else None,
            "blocks": blocks,
            "updated_at": iso(updated),
        }

    def event(self, tenant: Tenant, organizations: list, categories: list) -> dict[str, Any]:
        org = self.rng.choice(organizations)
        city = org["address"]["city"]
        name = self.rng.choice(vocab.EVENT_NAMES).format(org=org["name"], c=city)
        start = self.moment(days_back=300, days_forward=90)
        event_id = self.new_id()
        return {
            "id": event_id,
            "name": name,
            "summary_text": f"{name}, organisé par {org['name']}.",
            "canonical_url": f"https://{tenant.site}/evenements/{slugify(name)[:60]}-{event_id[:8]}",
            "starts_at": iso(start),
            "ends_at": iso(start + timedelta(hours=self.rng.randint(2, 8))),
            "address": self.address(city),
            "category_ids": [self.rng.choice(categories)["id"]],
            "organizer_ids": [org["id"]],
            "updated_at": iso(min(start, REFERENCE) - timedelta(days=self.rng.randint(1, 60))),
        }

    def project(self, tenant: Tenant, organizations: list, categories: list) -> dict[str, Any]:
        orgs = self.rng.sample(organizations, self.rng.randint(1, 3))
        name = self.rng.choice(vocab.PROJECT_NAMES).format(
            org=orgs[0]["name"], c=orgs[0]["address"]["city"]
        )
        project_id = self.new_id()
        return {
            "id": project_id,
            "name": name,
            "summary_text": f"Projet porté par {', '.join(o['name'] for o in orgs)}.",
            "canonical_url": f"https://{tenant.site}/projets/{slugify(name)[:60]}-{project_id[:8]}",
            "organization_ids": [o["id"] for o in orgs],
            "category_ids": [self.rng.choice(categories)["id"]],
            "updated_at": iso(self.moment()),
        }

    # ------------------------------------------------------------------ tenant

    def org_name(self, entity: OrgEntity) -> str:
        return f"{entity.base_name} {entity.suffix}".strip()

    # -------------------------------------------------------------- duplicates

    def name_variant(self, entity: OrgEntity) -> tuple[str, list[str]]:
        """Another source's spelling of the entity's name, and the changes applied."""
        original = self.org_name(entity)
        for _ in range(20):
            base, suffix, applied = entity.base_name, entity.suffix, []
            picks = self.rng.choices(NAME_CHANGES, NAME_CHANGE_WEIGHTS, k=self.rng.randint(1, 2))
            # Fixed order: the suffix lookup needs the suffix before case or accents change it.
            for change in (c for c in NAME_CHANGES if c in picks):
                before = (base, suffix)
                if change == "suffix":
                    suffix = self.rng.choice(vocab.SUFFIX_VARIANTS[suffix])
                elif change == "hyphen":
                    base = base.replace("-", " ")  # Saint-Georges, Saint Georges
                elif change == "ampersand":
                    swap = (" & ", " et ") if " & " in base else (" et ", " & ")
                    base = base.replace(*swap)
                elif change == "accents":
                    base, suffix = fold(base), fold(suffix)
                elif change == "case":
                    base, suffix = base.upper(), suffix.upper()
                if (base, suffix) != before:
                    applied.append(change)
            name = f"{base} {suffix}".strip()
            if name != original:
                return name, applied
        return original.upper(), ["case"]

    def duplicate_organization(
        self, entity: OrgEntity, profile_types: list, categories: list
    ) -> tuple[dict[str, Any], list[str]]:
        """A second record of `entity`, as another source would hold it."""
        name, changes = self.name_variant(entity)
        record = self.organization(entity, name, profile_types, categories)
        contact = record["contact"]
        if entity.domain and self.rng.random() < 0.3:
            record["canonical_domain"] = record["canonical_url"] = None
            contact["website"] = contact["email"] = None
            changes.append("missing_domain")
        if contact["linkedin"] and self.rng.random() < 0.4:
            contact["linkedin"] = None
            changes.append("missing_linkedin")
        if record["metadata"] and self.rng.random() < 0.5:
            record["metadata"] = []
            changes.append("missing_crm_id")
        return record, changes

    def duplicate_person(self, person: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        record, changes = copy.deepcopy(person), []
        record["id"] = self.new_id()
        record["canonical_url"] = f"{person['canonical_url']}-{record['id'][:4]}"
        record["updated_at"] = iso(self.moment())
        if "-" in record["first_name"]:
            record["first_name"] = record["first_name"].replace("-", " ")
            changes.append("hyphen")
        full = record["first_name"] + record["last_name"]
        if fold(full) != full:
            record["first_name"], record["last_name"] = (
                fold(record["first_name"]),
                fold(record["last_name"]),
            )
            changes.append("accents")
        if not changes:
            record["last_name"] = record["last_name"].upper()
            changes.append("case")
        if self.rng.random() < 0.5:
            record["contact"]["email"] = None
            changes.append("missing_email")
        return record, changes

    def tenant_entities(self, pool: list[OrgEntity], index: int) -> list[OrgEntity]:
        """Tenant 0 takes the start of the pool; tenant 1 shares part of it and adds its own."""
        size = self.sizes.organizations
        if index == 0:
            return pool[:size]
        shared = int(size * self.sizes.shared_share)
        return pool[:shared] + pool[size : size + size - shared]

    def tenant(self, tenant: Tenant, entities: list[OrgEntity]) -> TenantData:
        sizes = self.sizes
        categories, profile_types = self.categories(), self.profile_types()
        organizations, org_truth, original_ids = [], {}, {}
        for entity in entities:
            record = self.organization(entity, self.org_name(entity), profile_types, categories)
            organizations.append(record)
            org_truth[record["id"]] = entity.key
            original_ids[entity.key] = record["id"]
        org_duplicates = []
        dup_count = round(len(entities) * sizes.duplicate_org_share)
        for entity in self.rng.sample(entities, dup_count):
            record, changes = self.duplicate_organization(entity, profile_types, categories)
            organizations.append(record)
            org_truth[record["id"]] = entity.key
            org_duplicates.append(
                {
                    "entity": entity.key,
                    "record_ids": [original_ids[entity.key], record["id"]],
                    "changes": changes,
                }
            )
        self.rng.shuffle(organizations)

        people = [
            self.person(tenant, organizations, profile_types, journalist=i < sizes.authors)
            for i in range(sizes.people)
        ]
        authors = people[: sizes.authors]
        person_truth = {p["id"]: i for i, p in enumerate(people)}
        person_duplicates = []
        dup_count = round(sizes.people * sizes.duplicate_person_share)
        for index in self.rng.sample(range(sizes.authors, sizes.people), dup_count):
            record, changes = self.duplicate_person(people[index])
            people.append(record)
            person_truth[record["id"]] = index
            person_duplicates.append(
                {
                    "person": index,
                    "record_ids": [people[index]["id"], record["id"]],
                    "changes": changes,
                }
            )
        self.rng.shuffle(people)
        projects = [self.project(tenant, organizations, categories) for _ in range(sizes.projects)]
        events = [self.event(tenant, organizations, categories) for _ in range(sizes.events)]
        participants = {
            e["id"]: [p["id"] for p in self.rng.sample(people, self.rng.randint(0, 25))]
            for e in events
        }
        contents = [
            self.content(tenant, organizations, people, authors, categories)
            for _ in range(sizes.contents)
        ]
        data = TenantData(tenant)
        data.resources = {
            "categories": categories,
            "profile_types": profile_types,
            "organizations": organizations,
            "people": people,
            "projects": projects,
            "events": events,
            "contents": contents,
        }
        data.participants = participants
        # Organization keys are shared across tenants: the same key in both tenants'
        # ground truth is the same real-world organization.
        data.ground_truth = {
            "dev_only": True,
            "notice": GROUND_TRUTH_NOTICE,
            "organizations": org_truth,
            "organization_duplicates": org_duplicates,
            "people": person_truth,
            "person_duplicates": person_duplicates,
        }
        return data

    def generate(self) -> list[TenantData]:
        pool = self.org_entities(self.sizes.organizations * 2)
        return [self.tenant(t, self.tenant_entities(pool, i)) for i, t in enumerate(TENANTS)]


# ------------------------------------------------------------------- output


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_fixtures(tenants: list[TenantData], out_dir: Path, seed: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for data in tenants:
        tenant_dir = out_dir / data.tenant.media_id
        tenant_dir.mkdir(exist_ok=True)
        for kind, records in data.resources.items():
            (tenant_dir / f"{kind}.json").write_text(dump(records), encoding="utf-8")
        (tenant_dir / "participants.json").write_text(dump(data.participants), encoding="utf-8")
        (tenant_dir / GROUND_TRUTH_FILE).write_text(dump(data.ground_truth), encoding="utf-8")
    manifest = {
        "synthetic": True,
        "notice": NOTICE,
        "seed": seed,
        "reference_date": iso(REFERENCE),
        "tenants": [
            {
                "media_id": d.tenant.media_id,
                "name": d.tenant.name,
                "counts": {kind: len(records) for kind, records in d.resources.items()},
            }
            for d in tenants
        ],
    }
    (out_dir / "manifest.json").write_text(dump(manifest), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    parser.add_argument("--schemas", type=Path, help="also write JSON Schema files here")
    args = parser.parse_args(argv)

    write_fixtures(OmerloFixtureGenerator(args.seed).generate(), args.out, args.seed)
    if args.schemas:
        write_json_schemas(args.schemas)
    print(f"Wrote synthetic Omerlo fixtures (seed {args.seed}) to {args.out}")


if __name__ == "__main__":
    main()
