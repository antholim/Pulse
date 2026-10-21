import uuid

import pytest

from app.models import Source, SyncRun, Tenant
from app.seed import MOCK_OMERLO_BASE_URL
from app.sync import SyncCommandError, omerlo_settings, summary

TENANT = Tenant(id=uuid.uuid4(), name="Média démo Capitale", omerlo_media_id="demo-capitale")


def test_a_mock_source_uses_the_mock_key_of_its_tenant(monkeypatch):
    # Arrange
    monkeypatch.setenv("OMERLO_API_KEY", "staging-key")
    source = Source(kind="mock", config={"base_url": "http://mock-omerlo:8100/api"})

    # Act
    settings = omerlo_settings(source, TENANT)

    # Assert
    assert str(settings.base_url) == "http://mock-omerlo:8100/api"
    assert settings.api_key.get_secret_value() == "mock-demo-capitale"


def test_a_mock_source_without_a_base_url_points_at_the_local_mock():
    # Act
    settings = omerlo_settings(Source(kind="mock", config={}), TENANT)

    # Assert
    assert str(settings.base_url) == MOCK_OMERLO_BASE_URL


def test_a_mock_source_needs_a_tenant_slug():
    # Act / Assert
    with pytest.raises(SyncCommandError, match="slug"):
        omerlo_settings(Source(kind="mock", config={}), Tenant(name="No slug"))


def test_an_omerlo_source_reads_the_key_from_the_environment(monkeypatch):
    # Arrange
    monkeypatch.setenv("OMERLO_BASE_URL", "https://env.omerlo.test/api")
    monkeypatch.setenv("OMERLO_API_KEY", "staging-key")
    configured = Source(kind="omerlo", config={"base_url": "https://ca.omerlo.test/api"})

    # Act
    from_env = omerlo_settings(Source(kind="omerlo", config={}), TENANT)
    from_config = omerlo_settings(configured, TENANT)

    # Assert
    assert str(from_env.base_url) == "https://env.omerlo.test/api"
    assert str(from_config.base_url) == "https://ca.omerlo.test/api"
    assert from_config.api_key.get_secret_value() == "staging-key"


def test_other_source_kinds_cannot_be_synced():
    # Act / Assert
    with pytest.raises(SyncCommandError, match="csv"):
        omerlo_settings(Source(kind="csv", config={}), TENANT)


def test_summary_lists_the_counts_and_the_error():
    # Arrange
    run = SyncRun(
        id=uuid.UUID(int=1),
        mode="incremental",
        status="failed",
        counts={"fetched": 3},
        error="OmerloAuthError: rejected",
    )

    # Act
    text = summary(run)

    # Assert
    assert text == (
        f"Sync run {run.id} (incremental) failed: fetched 3, new 0, changed 0, unchanged 0, "
        "removed 0, failed 0\nOmerloAuthError: rejected"
    )
