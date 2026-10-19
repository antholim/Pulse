"""Load synthetic Omerlo fixtures, from files or straight from the generator."""

import json
from pathlib import Path

from synthetic.omerlo_fixtures import (
    DEFAULT_SEED,
    OmerloFixtureGenerator,
    Sizes,
    Tenant,
    TenantData,
)
from synthetic.omerlo_schema import MODELS


def load_fixtures(directory: Path) -> list[TenantData]:
    """Read fixtures written by `write_fixtures`. The dev-only ground truth is not loaded."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    tenants = []
    for entry in manifest["tenants"]:
        tenant_dir = directory / entry["media_id"]
        data = TenantData(Tenant(entry["media_id"], entry["name"], site=""))
        data.resources = {
            kind: json.loads((tenant_dir / f"{kind}.json").read_text(encoding="utf-8"))
            for kind in MODELS
        }
        data.participants = json.loads(
            (tenant_dir / "participants.json").read_text(encoding="utf-8")
        )
        tenants.append(data)
    return tenants


def generate_fixtures(seed: int = DEFAULT_SEED, sizes: Sizes | None = None) -> list[TenantData]:
    """Fixtures generated in memory, without the dev-only ground truth."""
    tenants = OmerloFixtureGenerator(seed, sizes).generate()
    for data in tenants:
        data.ground_truth = {}
    return tenants
