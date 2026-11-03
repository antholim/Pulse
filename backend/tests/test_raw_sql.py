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


def sql_argument(node: ast.Call) -> ast.expr | None:
    """The SQL passed to text() or exec_driver_sql(), by position or by keyword."""
    if node.args:
        return node.args[0]
    return next((k.value for k in node.keywords if k.arg in {"text", "statement"}), None)


def assignments(scope: ast.AST) -> dict[str, list[ast.expr]]:
    """Values assigned to each plain name directly in a module or function body."""
    found: dict[str, list[ast.expr]] = {}
    for node in ast.walk(scope):
        if node is not scope and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign | ast.AugAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        else:
            continue
        value = node.value
        if isinstance(node, ast.AugAssign):
            # sql += "..." builds a string whatever the right-hand side is.
            value = ast.BinOp(left=node.target, op=node.op, right=node.value)
        for name in targets:
            if value is not None:
                found.setdefault(name, []).append(value)
    return found


def builds_sql(argument: ast.expr, scopes: list[dict[str, list[ast.expr]]]) -> bool:
    """A built string passed inline, or a name assigned one in the same function or module."""
    if is_built_string(argument):
        return True
    if not isinstance(argument, ast.Name):
        return False
    for scope in reversed(scopes):
        if argument.id in scope:
            return any(is_built_string(value) for value in scope[argument.id])
    return False


def built_sql(path: Path) -> list[tuple[str, str, int]]:
    """(file, enclosing function, line) of every raw SQL call that gets a built string.

    A name is followed to its assignments in the same function or at module level. SQL
    built in another function and passed in as an argument is not caught.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    text_names = sqlalchemy_text_names(tree)
    relative = path.relative_to(APP).as_posix()
    found = []

    def visit(node: ast.AST, function: str, scopes: list[dict[str, list[ast.expr]]]) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            function = node.name
            scopes = [*scopes, assignments(node)]
        if isinstance(node, ast.Call) and is_raw_sql_call(node, text_names):
            argument = sql_argument(node)
            if argument is not None and builds_sql(argument, scopes):
                found.append((relative, function, node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child, function, scopes)

    visit(tree, "<module>", [assignments(tree)])
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
        'from sqlalchemy import text\ntext(text=f"SELECT {name}")',
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


@pytest.mark.parametrize(
    ("source", "line"),
    [
        ('from sqlalchemy import text\nsql = f"SELECT {name}"\ntext(sql)', 3),
        ('from sqlalchemy import text\nsql = "SELECT 1"\nsql += clause\ntext(sql)', 4),
        (
            "from sqlalchemy import text\ndef run(name):\n"
            '    sql: str = "SELECT " + name\n    return text(sql)',
            4,
        ),
    ],
)
def test_sql_built_on_an_earlier_line_is_detected(tmp_path, monkeypatch, source, line):
    # Arrange
    monkeypatch.setattr("tests.test_raw_sql.APP", tmp_path)
    path = tmp_path / "module.py"
    path.write_text(source, encoding="utf-8")

    # Act
    found = built_sql(path)

    # Assert
    assert [lineno for _, _, lineno in found] == [line]


def test_a_name_holding_literal_sql_passes(tmp_path, monkeypatch):
    # Arrange
    monkeypatch.setattr("tests.test_raw_sql.APP", tmp_path)
    path = tmp_path / "module.py"
    path.write_text(
        'from sqlalchemy import text\nSQL = "SELECT 1 WHERE id = :id"\ntext(SQL)', encoding="utf-8"
    )

    # Act / Assert
    assert built_sql(path) == []
