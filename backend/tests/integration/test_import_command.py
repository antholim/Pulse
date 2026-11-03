# AI contribution: 50% or more AI-generated
"""The import command against a real database."""

# Fixtures imported from test_sync_runs are redefined as test parameters on purpose.
# ruff: noqa: F811

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import import_file as import_command
from app import sync as sync_command
from app.models import Source, SyncRun
from app.seed import seed
from tests.integration.test_sync_runs import (  # noqa: F401
    SLUG,
    fixtures,
    mock_app,
    mock_client,
)

pytestmark = pytest.mark.integration

ORGANIZATIONS = (
    "id,name,website,email\n"
    "1,Acme inc.,acme.ca,info@acme.ca\n"
    "2,Beta,beta.ca,\n"
    "3,Gamma,,not-an-email\n"
)


@pytest.fixture
def seeded(migrated_database, tmp_path, monkeypatch):
    with Session(migrated_database) as setup:
        seed(setup)
        setup.commit()
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "archive"))
    return migrated_database


def write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def printed(capsys) -> list[str]:
    """What the commands printed, without the JSON log lines."""
    return [line for line in capsys.readouterr().out.splitlines() if not line.startswith("{")]


def csv_sources(database) -> int:
    with Session(database) as session:
        return session.scalar(select(func.count()).where(Source.kind == "csv"))


def test_the_first_import_creates_a_csv_source_and_lists_the_rejected_rows(
    seeded, tmp_path, capsys
):
    # Arrange
    path = write(tmp_path, "organizations.csv", ORGANIZATIONS)

    # Act
    import_command.main(["--tenant", SLUG, "--kind", "organization", path])

    # Assert
    lines = printed(capsys)
    assert "(incremental) succeeded: fetched 2, new 2" in lines[0]
    assert lines[0].endswith("failed 1")
    assert lines[1:] == ["Rejected rows:", "  row 4: email is not an email address"]
    assert csv_sources(seeded) == 1


def test_a_second_import_reuses_the_tenants_csv_source(seeded, tmp_path, capsys):
    # Arrange
    path = write(tmp_path, "organizations.csv", ORGANIZATIONS)
    import_command.main(["--tenant", SLUG, "--kind", "organization", path])

    # Act
    import_command.main(["--tenant", SLUG, "--kind", "organization", path, "--full"])

    # Assert
    second = printed(capsys)[3]
    assert "(full) succeeded: fetched 2, new 0, changed 0, unchanged 2, removed 0" in second
    assert csv_sources(seeded) == 1


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("organizations.csv", "id,website\n1,acme.ca\n", "missing required columns: name"),
        ("organizations.xlsx", "", "only .csv and .json files can be imported"),
    ],
)
def test_a_file_that_cannot_be_imported_records_no_run(
    seeded, tmp_path, capsys, name, text, message
):
    # Arrange
    path = write(tmp_path, name, text)

    # Act
    with pytest.raises(SystemExit) as exit_info:
        import_command.main(["--tenant", SLUG, "--kind", "organization", path])

    # Assert
    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err
    with Session(seeded) as session:
        assert session.scalar(select(func.count()).select_from(SyncRun)) == 0


def test_a_missing_file_is_reported(seeded, tmp_path, capsys):
    # Act
    with pytest.raises(SystemExit) as exit_info:
        import_command.main(["--tenant", SLUG, "--kind", "person", str(tmp_path / "none.csv")])

    # Assert
    assert exit_info.value.code == 2
    assert "Cannot read" in capsys.readouterr().err


def test_the_sync_command_ignores_the_csv_source(seeded, mock_app, tmp_path, monkeypatch, capsys):
    # Arrange
    path = write(tmp_path, "organizations.csv", ORGANIZATIONS)
    import_command.main(["--tenant", SLUG, "--kind", "organization", path])
    monkeypatch.setattr(
        sync_command, "create_omerlo_client", lambda settings: mock_client(mock_app, SLUG)
    )

    # Act
    sync_command.main(["--tenant", SLUG, "--full"])

    # Assert
    assert "(full) succeeded" in printed(capsys)[-1]
