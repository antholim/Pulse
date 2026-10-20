"""Seed the local database with two demo tenants, each with one mock source.

The tenants match the synthetic fixtures served by the mock Omerlo server (#51), so a
sync can run against it locally. Safe to run more than once.

    uv run python -m app.seed
"""

import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.models import Source, Tenant

MOCK_OMERLO_BASE_URL = "http://localhost:8100/api"


@dataclass(frozen=True)
class DemoTenant:
    omerlo_media_id: str
    name: str


# Same slugs and names as TENANTS in synthetic/omerlo_fixtures.py.
DEMO_TENANTS = (
    DemoTenant("demo-capitale", "Média démo Capitale"),
    DemoTenant("demo-estrie", "Média démo Estrie"),
)


def mock_source_config() -> dict:
    # The API key is not stored here; the connector reads it from the environment.
    return {"base_url": os.environ.get("OMERLO_BASE_URL") or MOCK_OMERLO_BASE_URL}


def seed(session: Session) -> list[str]:
    """Create the missing demo tenants and mock sources; return what was created."""
    created = []
    for demo in DEMO_TENANTS:
        tenant = session.scalar(
            select(Tenant).where(Tenant.omerlo_media_id == demo.omerlo_media_id)
        )
        if tenant is None:
            tenant = Tenant(name=demo.name, omerlo_media_id=demo.omerlo_media_id)
            session.add(tenant)
            session.flush()
            created.append(f"tenant {demo.omerlo_media_id}")

        has_mock_source = session.scalar(
            select(Source.id).where(Source.tenant_id == tenant.id, Source.kind == "mock")
        )
        if has_mock_source is None:
            session.add(Source(tenant_id=tenant.id, kind="mock", config=mock_source_config()))
            created.append(f"mock source for {demo.omerlo_media_id}")
    return created


def main() -> None:
    with get_session_factory()() as session:
        created = seed(session)
        session.commit()
    print("\n".join(f"Created {item}" for item in created) or "Nothing to seed")


if __name__ == "__main__":
    main()
