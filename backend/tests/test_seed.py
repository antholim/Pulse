from app.seed import DEMO_TENANTS, MOCK_OMERLO_BASE_URL, mock_source_config
from synthetic.omerlo_fixtures import TENANTS


def test_demo_tenants_match_the_synthetic_fixtures():
    assert [(t.omerlo_media_id, t.name) for t in DEMO_TENANTS] == [
        (t.media_id, t.name) for t in TENANTS
    ]


def test_mock_source_points_at_the_local_mock_server(monkeypatch):
    monkeypatch.delenv("OMERLO_BASE_URL", raising=False)

    assert mock_source_config() == {"base_url": MOCK_OMERLO_BASE_URL}


def test_mock_source_follows_omerlo_base_url(monkeypatch):
    monkeypatch.setenv("OMERLO_BASE_URL", "http://mock-omerlo:8100/api")

    assert mock_source_config() == {"base_url": "http://mock-omerlo:8100/api"}
