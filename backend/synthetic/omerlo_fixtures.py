"""Seeded generator of synthetic Omerlo backoffice API fixtures for two tenants.

    uv run python -m synthetic.omerlo_fixtures --seed 490 --out synthetic/out

Writes `<out>/<tenant>/<kind>.json` with the detail records of every resource in
`omerlo_schema.MODELS`, `metadata.json` per tenant (record id to key and value
entries, served apart from the record), `manifest.json`, and a dev-only
`ground_truth.dev_only.json` per tenant listing the deliberate duplicates.
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
from synthetic.omerlo_schema import METADATA_FILE, write_json_schemas

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
TIMEZONE = "America/Montreal"

# Ways another source may spell the same organization name, and how often each is picked.
NAME_CHANGES = ("suffix", "accents", "case", "hyphen", "ampersand")
NAME_CHANGE_WEIGHTS = (4, 3, 1, 2, 1)

# Locales a record is written in, and how often: most are French, many bilingual.
LOCALE_SETS = (("fr",), ("fr", "en"), ("en",))
LOCALE_WEIGHTS = (5, 4, 1)

CONTACT_FIELDS = (
    "email", "phone", "facebook", "linkedin", "instagram", "twitter", "bluesky", "website"
)  # fmt: skip


@dataclass(frozen=True)
class Tenant:
    slug: str
    name: str
    site: str
    # Omerlo workspaces of this client; records are spread across them.
    workspaces: tuple[str, ...]


TENANTS = (
    Tenant("demo-capitale", "Média démo Capitale", "capitale.example", ("Capitale", "Affaires")),
    Tenant("demo-estrie", "Média démo Estrie", "estrie.example", ("Estrie",)),
)


@dataclass(frozen=True)
class Sizes:
    organizations: int = 150
    people: int = 300
    events: int = 60
    projects: int = 20
    journalists: int = 15
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
    # Record id -> metadata entries; records without metadata are left out.
    metadata: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    ground_truth: dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    """Per-tenant reference data the record builders draw from."""

    tenant: Tenant
    workspaces: list[dict[str, Any]]
    categories: list[dict[str, Any]]
    profile_types: dict[str, str]


def fold(text: str) -> str:
    """Drop accents, keeping case: `Québec` becomes `Quebec`."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(text).lower()).strip("-")


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def domain_of(url: str | None) -> str | None:
    return url.removeprefix("https://").removeprefix("www.").split("/")[0] if url else None


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

    def timestamps(self) -> dict[str, str]:
        inserted = self.moment(days_back=730)
        updated = inserted + (REFERENCE - inserted) * self.rng.random()
        return {"inserted_at": iso(inserted), "updated_at": iso(updated)}

    def locales(self) -> tuple[str, ...]:
        return self.rng.choices(LOCALE_SETS, LOCALE_WEIGHTS)[0]

    def phone(self) -> str:
        # 555 exchanges are reserved for fiction.
        return f"+1 418 555 {self.rng.randint(0, 9999):04d}"

    def postal_code(self, city: str) -> str:
        letters = "ABCEGHJKLMNPRSTVXY"
        r = self.rng
        first = f"{vocab.POSTAL_PREFIX[city]}{r.randint(0, 9)}{r.choice(letters)}"
        return f"{first} {r.randint(0, 9)}{r.choice(letters)}{r.randint(0, 9)}"

    def addresses(self, city: str, locales: tuple[str, ...]) -> list[dict[str, Any]]:
        street = f"{self.rng.randint(1, 9999)} {self.rng.choice(vocab.STREETS)}"
        location = self.postal_code(city)
        return [
            {
                "id": self.new_id(),
                "locale": locale,
                "street": street,
                "location": location,
                "city": city,
                "country": "Canada",
                "deleted_at": None,
            }
            for locale in locales
        ]

    def contacts(self, locales: tuple[str, ...], **values: str | None) -> list[dict[str, Any]]:
        """One entry per locale; only the website changes, to the English version."""
        entries = []
        for locale in locales:
            entry = {"id": self.new_id(), "locale": locale, **dict.fromkeys(CONTACT_FIELDS)}
            entry.update(values, deleted_at=None)
            if locale == "en" and entry["website"]:
                entry["website"] += "/en"
            entries.append(entry)
        return entries

    def descriptions(self, locales: tuple[str, ...], text: dict[str, str]) -> list[dict[str, Any]]:
        return [
            {
                "id": self.new_id(),
                "locale": locale,
                "blocks": [
                    {
                        "kind": "richtext",
                        "content_html": f"<p>{text[locale]}</p>",
                        "content_text": text[locale],
                        "image": None,
                        "slideshow": None,
                        "video": None,
                    }
                ],
                "deleted_at": None,
            }
            for locale in locales
        ]

    def profile(
        self, record_id: str, ctx: Context, profile_type: str, url: str | None, categories: int
    ) -> dict[str, Any]:
        # Most records live in the first workspace; the others hold the rest.
        weights = [4] + [1] * (len(ctx.workspaces) - 1)
        workspace = self.rng.choices(ctx.workspaces, weights)[0]
        draft, published = (s["id"] for s in workspace["statuses"])
        return {
            "id": record_id,
            "workspace_id": workspace["id"],
            "profile_categories": [
                {"id": self.new_id(), "category_id": c["id"]}
                for c in self.rng.sample(ctx.categories, categories)
            ],
            "profile_type_id": ctx.profile_types[profile_type],
            "status_id": draft if self.rng.random() < 0.1 else published,
            "canonical_url": url,
        }

    def profile_fields(self, ctx: Context, **profile_args: Any) -> dict[str, Any]:
        record_id = self.new_id()
        return {
            "id": record_id,
            "profile_image_key": f"images/{record_id}.jpg" if self.rng.random() < 0.6 else None,
            "cover_image_key": None,
            "profile": self.profile(record_id, ctx, **profile_args),
            **self.timestamps(),
        }

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

    def workspace(self, tenant: Tenant, name: str, index: int) -> dict[str, Any]:
        host = tenant.site if index == 0 else f"{slugify(name)}.{tenant.site}"
        statuses = [
            self.status("Brouillon", "Draft", completed=False, position=0),
            self.status("Publié", "Published", completed=True, position=1),
        ]
        return {
            "id": self.new_id(),
            "name": name,
            "canonical_domain": f"https://{host}",
            "locales": [
                {
                    "id": self.new_id(),
                    "locale": locale,
                    "description": f"{name} ({tenant.name})",
                    "deleted_at": None,
                }
                for locale in ("fr", "en")
            ],
            "statuses": statuses,
            "inserted_at": iso(REFERENCE - timedelta(days=900)),
            "updated_at": iso(REFERENCE - timedelta(days=30)),
        }

    def status(self, name_fr: str, name_en: str, completed: bool, position: int) -> dict:
        moment = iso(REFERENCE - timedelta(days=900))
        return {
            "id": self.new_id(),
            "color": "#2E7D32" if completed else "#9E9E9E",
            "text_color": "#FFFFFF",
            "completed": completed,
            "locales": [
                {
                    "id": self.new_id(),
                    "locale": locale,
                    "name": name,
                    "description": None,
                    "deleted_at": None,
                }
                for locale, name in (("fr", name_fr), ("en", name_en))
            ],
            "position": position,
            "inserted_at": moment,
            "updated_at": moment,
        }

    def categories(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self.new_id(),
                "locales": [
                    {
                        "id": self.new_id(),
                        "locale": locale,
                        "name": name,
                        "description": None,
                        "deleted_at": None,
                    }
                    for locale, name in (("fr", fr), ("en", en))
                ],
                "svg_icon": None,
                "deleted_at": None,
                "is_archived": False,
                "is_unlisted": False,
                **self.timestamps(),
            }
            for fr, en in vocab.CATEGORIES
        ]

    def profile_types(self) -> dict[str, str]:
        # Only the company type carries a CRM id, used as an external id for matching.
        return {
            kind: self.new_id() for kind in ("company", "organisme", "person", "event", "project")
        }

    def organization(
        self, entity: OrgEntity, name: str, ctx: Context
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """The record and its metadata entries."""
        profile_type = "company" if entity.crm_id else self.rng.choice(["company", "organisme"])
        domain = entity.domain
        website = f"https://www.{domain}" if domain else None
        locales = self.locales()
        record = {
            **self.profile_fields(
                ctx,
                profile_type=profile_type,
                url=website,
                categories=self.rng.randint(1, 2),
            ),
            "name": name,
            "description": self.descriptions(
                locales,
                {"fr": f"Présentation de {entity.base_name}.", "en": f"About {entity.base_name}."},
            ),
            "address": self.addresses(entity.city, locales),
            "contact": self.contacts(
                locales,
                email=f"info@{domain}" if domain else None,
                phone=self.phone(),
                linkedin=entity.linkedin,
                website=website,
            ),
            "locales": [
                {
                    "id": self.new_id(),
                    "locale": locale,
                    "summary_html": f"<p>{entity.base_name}, {entity.city}.</p>",
                    "deleted_at": None,
                }
                for locale in locales
            ],
        }
        metadata = []
        if entity.crm_id and profile_type == "company":
            metadata.append({"key": "crm_id", "value": entity.crm_id})
        return record, metadata

    def person(self, ctx: Context, employer: dict[str, Any], journalist: bool) -> dict[str, Any]:
        first, last = self.rng.choice(vocab.FIRST_NAMES), self.rng.choice(vocab.LAST_NAMES)
        domain = ctx.tenant.site if journalist else domain_of(employer["profile"]["canonical_url"])
        city = employer["address"][0]["city"]
        slug = slugify(f"{first} {last}")
        locales = self.locales()
        job_title = "Journaliste" if journalist else self.rng.choice(vocab.JOB_TITLES)
        return {
            **self.profile_fields(
                ctx,
                profile_type="person",
                url=f"https://{ctx.tenant.site}/personnes/{slug}",
                categories=0,
            ),
            "first_name": first,
            "last_name": last,
            "other_name": None,
            "pronoun": self.rng.choice([None, None, "elle", "il", "iel"]),
            "description": [],
            "address": self.addresses(city, locales),
            "contact": self.contacts(
                locales,
                email=f"{slug.replace('-', '.')}@{domain}" if domain else None,
                linkedin=f"https://www.linkedin.com/in/{slug}" if self.rng.random() < 0.5 else None,
            ),
            "locales": [
                {
                    "id": self.new_id(),
                    "locale": locale,
                    "job_title": job_title,
                    "summary_html": None,
                    "deleted_at": None,
                }
                for locale in locales
            ],
        }

    def named_locales(self, locales: tuple[str, ...], name: str, summary: str) -> list[dict]:
        return [
            {
                "id": self.new_id(),
                "locale": locale,
                "name": name,
                "summary_html": f"<p>{summary}</p>",
                "deleted_at": None,
            }
            for locale in locales
        ]

    def event(self, ctx: Context, host: dict[str, Any]) -> dict[str, Any]:
        city = host["address"][0]["city"]
        name = self.rng.choice(vocab.EVENT_NAMES).format(org=host["name"], c=city)
        start = self.moment(days_back=300, days_forward=90)
        end = start + timedelta(hours=self.rng.randint(2, 8))
        locales = self.locales()
        record = {
            **self.profile_fields(
                ctx,
                profile_type="event",
                url=f"https://{ctx.tenant.site}/evenements/{slugify(name)[:60]}",
                categories=1,
            ),
            "subscription_url": None,
            "schedule": {
                "id": self.new_id(),
                "recurrence": "none",
                "frequency": "daily",
                "interval": 1,
                "starts_at_date": start.date().isoformat(),
                "starts_at_time": start.time().isoformat(),
                "ends_at_date": end.date().isoformat(),
                "ends_at_time": end.time().isoformat(),
                "all_day": False,
                "count": 730,
                "until": None,
                "timezone": TIMEZONE,
                "excluded_dates": [],
                "days": [],
                "monthly_opts": "monthly",
            },
            "description": self.descriptions(
                locales, {"fr": f"{name}, organisé par {host['name']}.", "en": f"{name}."}
            ),
            "address": self.addresses(city, locales),
            "contact": self.contacts(locales, email=host["contact"][0]["email"]),
            "locales": self.named_locales(locales, name, f"{name}, à {city}."),
            "form": {"id": self.new_id(), "blocks": []},
            "registration_open": False,
            "registration_opens_at": None,
            "registration_closes_at": None,
            "registration_timezone": None,
        }
        # An event is last edited before it starts.
        record["updated_at"] = min(record["updated_at"], iso(start))
        record["inserted_at"] = min(record["inserted_at"], record["updated_at"])
        return record

    def sessions(self, event: dict[str, Any], people: list) -> list[dict[str, Any]]:
        schedule = event["schedule"]
        start = datetime.fromisoformat(
            f"{schedule['starts_at_date']}T{schedule['starts_at_time']}+00:00"
        )
        sessions = []
        for index in range(self.rng.randint(1, 3)):
            starts_at = start + timedelta(hours=index)
            speakers = self.rng.sample(people, self.rng.randint(0, 3))
            title = f"Séance {index + 1}"
            sessions.append(
                {
                    "id": self.new_id(),
                    "event_id": event["id"],
                    "location": event["address"][0]["street"],
                    "starts_at": iso(starts_at),
                    "ends_at": iso(starts_at + timedelta(minutes=50)),
                    "timezone": TIMEZONE,
                    "locales": [
                        {
                            "id": self.new_id(),
                            "locale": locale["locale"],
                            "title_html": title,
                            "description_html": None,
                            "deleted_at": None,
                        }
                        for locale in event["locales"]
                    ],
                    "session_speakers": [
                        {"id": self.new_id(), "position": position, "actor_id": person["id"]}
                        for position, person in enumerate(speakers)
                    ],
                    "inserted_at": event["inserted_at"],
                    "updated_at": event["updated_at"],
                }
            )
        return sessions

    def project(self, ctx: Context, owner: dict[str, Any]) -> dict[str, Any]:
        city = owner["address"][0]["city"]
        name = self.rng.choice(vocab.PROJECT_NAMES).format(org=owner["name"], c=city)
        locales = self.locales()
        return {
            **self.profile_fields(
                ctx,
                profile_type="project",
                url=f"https://{ctx.tenant.site}/projets/{slugify(name)[:60]}",
                categories=1,
            ),
            "owner_id": owner["id"],
            "description": self.descriptions(
                locales, {"fr": f"Projet porté par {owner['name']}.", "en": f"{name}."}
            ),
            "address": self.addresses(city, locales),
            "contact": [],
            "locales": self.named_locales(locales, name, f"Projet de {owner['name']}."),
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
        self, entity: OrgEntity, ctx: Context
    ) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
        """A second record of `entity`, as another source would hold it, possibly in
        another workspace."""
        name, changes = self.name_variant(entity)
        record, metadata = self.organization(entity, name, ctx)
        if entity.domain and self.rng.random() < 0.3:
            record["profile"]["canonical_url"] = None
            for contact in record["contact"]:
                contact["website"] = contact["email"] = None
            changes.append("missing_domain")
        if entity.linkedin and self.rng.random() < 0.4:
            for contact in record["contact"]:
                contact["linkedin"] = None
            changes.append("missing_linkedin")
        if metadata and self.rng.random() < 0.5:
            metadata = []
            changes.append("missing_crm_id")
        return record, metadata, changes

    def duplicate_person(self, person: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        record, changes = copy.deepcopy(person), []
        record["id"] = record["profile"]["id"] = self.new_id()
        record["profile"]["canonical_url"] = f"{person['profile']['canonical_url']}-2"
        record.update(self.timestamps())
        for entry in (*record["contact"], *record["address"], *record["locales"]):
            entry["id"] = self.new_id()
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
        if record["contact"] and record["contact"][0]["email"] and self.rng.random() < 0.5:
            for contact in record["contact"]:
                contact["email"] = None
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
        ctx = Context(
            tenant=tenant,
            workspaces=[
                self.workspace(tenant, name, i) for i, name in enumerate(tenant.workspaces)
            ],
            categories=self.categories(),
            profile_types=self.profile_types(),
        )
        data = TenantData(tenant)

        organizations, org_truth, original_ids = [], {}, {}
        for entity in entities:
            record, metadata = self.organization(entity, self.org_name(entity), ctx)
            organizations.append(record)
            if metadata:
                data.metadata[record["id"]] = metadata
            org_truth[record["id"]] = entity.key
            original_ids[entity.key] = record["id"]
        org_duplicates = []
        dup_count = round(len(entities) * sizes.duplicate_org_share)
        for entity in self.rng.sample(entities, dup_count):
            record, metadata, changes = self.duplicate_organization(entity, ctx)
            organizations.append(record)
            if metadata:
                data.metadata[record["id"]] = metadata
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
            self.person(ctx, self.rng.choice(organizations), journalist=i < sizes.journalists)
            for i in range(sizes.people)
        ]
        person_truth = {p["id"]: i for i, p in enumerate(people)}
        person_duplicates = []
        dup_count = round(sizes.people * sizes.duplicate_person_share)
        for index in self.rng.sample(range(sizes.journalists, sizes.people), dup_count):
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

        projects = [
            self.project(ctx, self.rng.choice(organizations)) for _ in range(sizes.projects)
        ]
        events = [self.event(ctx, self.rng.choice(organizations)) for _ in range(sizes.events)]
        sessions = [s for e in events for s in self.sessions(e, people)]
        data.resources = {
            "workspaces": ctx.workspaces,
            "categories": ctx.categories,
            "organizations": organizations,
            "people": people,
            "projects": projects,
            "events": events,
            "event_sessions": sessions,
        }
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
        tenant_dir = out_dir / data.tenant.slug
        tenant_dir.mkdir(exist_ok=True)
        for kind, records in data.resources.items():
            (tenant_dir / f"{kind}.json").write_text(dump(records), encoding="utf-8")
        (tenant_dir / f"{METADATA_FILE}.json").write_text(dump(data.metadata), encoding="utf-8")
        (tenant_dir / GROUND_TRUTH_FILE).write_text(dump(data.ground_truth), encoding="utf-8")
    manifest = {
        "synthetic": True,
        "notice": NOTICE,
        "seed": seed,
        "reference_date": iso(REFERENCE),
        "tenants": [
            {
                "slug": d.tenant.slug,
                "name": d.tenant.name,
                "site": d.tenant.site,
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
