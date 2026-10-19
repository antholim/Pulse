"""Seeded generator of synthetic Omerlo Reader API fixtures for two tenants.

    uv run python -m synthetic.omerlo_fixtures --seed 490 --out synthetic/out

Writes `<out>/<media id>/<kind>.json` for every resource in `omerlo_schema.MODELS`,
`participants.json` per tenant (event id to person ids), and `manifest.json`.
The same seed always produces byte-identical files. All data is invented.
"""

import argparse
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


def slugify(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


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
        organizations = [
            self.organization(e, self.org_name(e), profile_types, categories) for e in entities
        ]
        people = [
            self.person(tenant, organizations, profile_types, journalist=i < sizes.authors)
            for i in range(sizes.people)
        ]
        authors = people[: sizes.authors]
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
