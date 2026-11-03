# AI contribution: 50% or more AI-generated
import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
CONSTANT = re.compile(r"^_?[A-Z][A-Z0-9_]*$")

# (file, function) pairs allowed to build SQL from a string expression, with the reason.
ALLOWED = {
    ("models/base.py", "json_column"): "server default built from a literal in the model code",
}


def sqlalchemy_text_names(tree: ast.Module) -> set[str]:
    """Local names bound to sqlalchemy's text() in a module."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy"):
            names.update(alias.asname or alias.name for alias in node.names if alias.name == "text")
    return names


def only_inserts_constants(node: ast.JoinedStr) -> bool:
    """An f-string whose placeholders are all UPPER_CASE constants, such as a shared fragment."""
    values = [part.value for part in node.values if isinstance(part, ast.FormattedValue)]
    return all(isinstance(value, ast.Name) and CONSTANT.match(value.id) for value in values)


def is_built_string(node: ast.expr) -> bool:
    """An f-string with a variable in it, a concatenation or %-formatting, or str.format()."""
    if isinstance(node, ast.JoinedStr):
        return not only_inserts_constants(node)
    if isinstance(node, ast.BinOp):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    )


def is_raw_sql_call(node: ast.Call, text_names: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in text_names
    return isinstance(func, ast.Attribute) and func.attr in {"text", "exec_driver_sql"}


def built_sql(path: Path) -> list[tuple[str, str, int]]:
    """(file, enclosing function, line) of every raw SQL call that gets a built string."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    text_names = sqlalchemy_text_names(tree)
    relative = path.relative_to(APP).as_posix()
    found = []

    def visit(node: ast.AST, function: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            function = node.name
        if (
            isinstance(node, ast.Call)
            and node.args
            and is_raw_sql_call(node, text_names)
            and is_built_string(node.args[0])
        ):
            found.append((relative, function, node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, "<module>")
    return found


def test_raw_sql_is_never_built_from_strings():
    # Arrange
    sources = sorted(APP.rglob("*.py"))

    # Act
    violations = [
        f"{file}:{line} in {function}"
        for path in sources
        for file, function, line in built_sql(path)
        if (file, function) not in ALLOWED
    ]

    # Assert
    assert violations == [], "Pass values as bound parameters instead of building SQL strings"


@pytest.mark.parametrize(
    "source",
    [
        'from sqlalchemy import text\ntext(f"SELECT {name}")',
        'from sqlalchemy import text\ntext("SELECT " + name)',
        'from sqlalchemy import text\ntext("SELECT %s" % name)',
        'from sqlalchemy import text as sql\nsql("SELECT {}".format(name))',
        'import sqlalchemy\nsqlalchemy.text(f"SELECT {name}")',
        'conn.exec_driver_sql(f"SELECT {name}")',
    ],
)
def test_built_sql_is_detected(tmp_path, monkeypatch, source):
    # Arrange
    monkeypatch.setattr("tests.test_raw_sql.APP", tmp_path)
    path = tmp_path / "module.py"
    path.write_text(source, encoding="utf-8")

    # Act / Assert
    assert built_sql(path) == [("module.py", "<module>", 2 if "\n" in source else 1)]


@pytest.mark.parametrize(
    "source",
    [
        'from sqlalchemy import text\ntext("SELECT 1 WHERE id = :id")',
        'def text(value):\n    return value\ntext(f"not {sql}")',
        'from sqlalchemy import text\ntext(f"SELECT * FROM {_FRAGMENT} WHERE id = :id")',
    ],
)
def test_literal_sql_and_other_text_functions_pass(tmp_path, monkeypatch, source):
    # Arrange
    monkeypatch.setattr("tests.test_raw_sql.APP", tmp_path)
    path = tmp_path / "module.py"
    path.write_text(source, encoding="utf-8")

    # Act / Assert
    assert built_sql(path) == []
