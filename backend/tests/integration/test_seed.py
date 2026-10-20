import pytest
from sqlalchemy import select

from app import seed as seed_module
from app.models import Source, Tenant
from app.seed import DEMO_TENANTS, seed

pytestmark = pytest.mark.integration


def test_seed_creates_two_tenants_with_one_mock_source_each(session):
    created = seed(session)

    tenants = session.scalars(select(Tenant).order_by(Tenant.omerlo_media_id)).all()
    assert [t.omerlo_media_id for t in tenants] == [t.omerlo_media_id for t in DEMO_TENANTS]
    for tenant in tenants:
        sources = session.scalars(select(Source).where(Source.tenant_id == tenant.id)).all()
        assert [s.kind for s in sources] == ["mock"]
        assert sources[0].config["base_url"]
    assert len(created) == 4


def test_seed_twice_creates_nothing_the_second_time(session):
    seed(session)

    assert seed(session) == []
    assert len(session.scalars(select(Source)).all()) == 2


def test_seed_command_commits_and_reports(migrated_database, capsys):
    seed_module.main()
    seed_module.main()

    first, second = capsys.readouterr().out.strip().split("\n", 4)[-2:]
    assert "Created mock source for demo-estrie" in first
    assert second == "Nothing to seed"
