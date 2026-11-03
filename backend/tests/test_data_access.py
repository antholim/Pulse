# AI contribution: 50% or more AI-generated
"""Raw SQL stays in the data access layer, where the tenant rules are reviewed."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

# Where raw SQL may live: the services and storage that read and write tenant data, the
# model definitions (server defaults, index predicates) and the engine setup.
DATA_ACCESS = ("services/", "storage/", "models/", "core/database.py")


def is_raw_sql_call(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr == "exec_driver_sql":
        return True
    owner = node.func.value
    return (
        node.func.attr == "text"
        and isinstance(owner, ast.Name)
        and owner.id in {"sqlalchemy", "sa"}
    )


def imports_text(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("sqlalchemy")
        and any(alias.name == "text" for alias in node.names)
    )


def raw_sql_uses(path: Path) -> list[int]:
    """Lines that import sqlalchemy's text() or call text() / exec_driver_sql()."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.lineno for node in ast.walk(tree) if imports_text(node) or is_raw_sql_call(node)]


def in_data_access(relative: str) -> bool:
    return relative.startswith(DATA_ACCESS)


def test_raw_sql_is_only_used_in_the_data_access_layer():
    # Arrange
    sources = sorted(APP.rglob("*.py"))

    # Act
    outside = [
        f"{relative}:{line}"
        for path in sources
        if not in_data_access(relative := path.relative_to(APP).as_posix())
        for line in raw_sql_uses(path)
    ]

    # Assert
    assert outside == [], "Move raw SQL into app/services or app/storage"


@pytest.mark.parametrize(
    "source",
    [
        "from sqlalchemy import select, text",
        "import sqlalchemy\nsqlalchemy.text('SELECT 1')",
        "import sqlalchemy as sa\nsa.text('SELECT 1')",
        "connection.exec_driver_sql('SELECT 1')",
    ],
)
def test_raw_sql_is_detected(tmp_path, source):
    # Arrange
    path = tmp_path / "module.py"
    path.write_text(source, encoding="utf-8")

    # Act / Assert
    assert raw_sql_uses(path)


def test_other_text_helpers_are_not_raw_sql(tmp_path):
    # Arrange: the Omerlo field mapping has its own text() helper.
    path = tmp_path / "module.py"
    path.write_text("def text(value):\n    return value\ntext('x')", encoding="utf-8")

    # Act / Assert
    assert raw_sql_uses(path) == []


@pytest.mark.parametrize(
    ("relative", "allowed"),
    [
        ("services/source_records.py", True),
        ("storage/raw_records.py", True),
        ("models/base.py", True),
        ("core/database.py", True),
        ("api/browse.py", False),
        ("core/security.py", False),
        ("sync.py", False),
    ],
)
def test_the_data_access_layer(relative, allowed):
    # Act / Assert
    assert in_data_access(relative) is allowed
