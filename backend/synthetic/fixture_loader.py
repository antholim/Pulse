"""Load synthetic Omerlo fixtures, from files or straight from the generator."""

import json
from pathlib import Path
from typing import Any

from synthetic.omerlo_fixtures import (
    DEFAULT_SEED,
    OmerloFixtureGenerator,
    Sizes,
    Tenant,
    TenantData,
)
from synthetic.omerlo_schema import METADATA_FILE, MODELS


def load_fixtures(directory: Path) -> list[TenantData]:
    """Read fixtures written by `write_fixtures`. The dev-only ground truth is not loaded."""
    tenants = []
    for entry in read_json(directory / "manifest.json")["tenants"]:
        tenant_dir = directory / entry["slug"]
        resources = {kind: read_json(tenant_dir / f"{kind}.json") for kind in MODELS}
        workspaces = tuple(w["name"] for w in resources["workspaces"])
        tenant = Tenant(entry["slug"], entry["name"], entry["site"], workspaces)
        metadata = read_json(tenant_dir / f"{METADATA_FILE}.json")
        tenants.append(TenantData(tenant, resources, metadata))
    return tenants


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def generate_fixtures(seed: int = DEFAULT_SEED, sizes: Sizes | None = None) -> list[TenantData]:
    """Fixtures generated in memory, without the dev-only ground truth."""
    tenants = OmerloFixtureGenerator(seed, sizes).generate()
    for data in tenants:
        data.ground_truth = {}
    return tenants
