import uuid

from fastapi.testclient import TestClient

from app.api.browse import database as browse_database
from app.core import database
from app.main import app
from app.models import SourceRecord
from app.services.browse import label


def record(kind: str, attributes: dict, name_normalized: str | None = "fallback") -> SourceRecord:
    return SourceRecord(
        kind=kind, external_id="ext-1", attributes=attributes, name_normalized=name_normalized
    )


def test_organization_label_is_its_stored_name():
    # Arrange
    org = record("organization", {"name": "Groupe Tremblay inc."})

    # Act / Assert
    assert label(org) == "Groupe Tremblay inc."


def test_person_label_joins_first_and_last_name():
    # Arrange
    person = record("person", {"first_name": "Émilie", "last_name": "Gagnon"})

    # Act / Assert
    assert label(person) == "Émilie Gagnon"


def test_event_label_is_its_first_locale_name():
    # Arrange
    event = record("event", {"locales": [{"locale": "fr", "name": "Gala annuel"}]})

    # Act / Assert
    assert label(event) == "Gala annuel"


def test_label_falls_back_to_the_normalized_name_then_the_id():
    # Arrange
    named = record("organization", {})
    unnamed = record("project", {}, name_normalized=None)

    # Act / Assert
    assert (label(named), label(unnamed)) == ("fallback", "ext-1")


def test_endpoints_answer_503_without_a_database(monkeypatch):
    # Arrange
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()
    client = TestClient(app)

    # Act
    try:
        response = client.get(f"/api/tenants/{uuid.uuid4()}/runs")
    finally:
        database.get_engine.cache_clear()
        database.get_session_factory.cache_clear()

    # Assert
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_unknown_kind_is_rejected():
    # Arrange
    app.dependency_overrides[browse_database] = lambda: None
    client = TestClient(app)

    # Act
    try:
        response = client.get(f"/api/tenants/{uuid.uuid4()}/records", params={"kind": "subscriber"})
    finally:
        app.dependency_overrides.clear()

    # Assert
    assert response.status_code == 422
