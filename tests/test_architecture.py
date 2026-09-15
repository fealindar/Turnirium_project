import ast
import io
import re
import tokenize
from pathlib import Path

from app.routes.schemas import CategoryIn


ROOT = Path(__file__).resolve().parents[1]


def test_source_modules_remain_reviewable_in_size():
    """Защищает проект от повторного появления монолитов на тысячи строк."""
    oversized = []
    for pattern in ("app/**/*.py", "app/static/*.js", "app/static/*.css"):
        for path in ROOT.glob(pattern):
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            if line_count > 600:
                oversized.append(f"{path.relative_to(ROOT)}: {line_count}")
    assert not oversized, "Слишком крупные модули:\n" + "\n".join(oversized)
    assert not (ROOT / "app" / "static" / "app.js").exists()


def test_category_schema_rejects_invalid_rule_payloads():
    base = {"name": "Сабля", "format": "knockout"}
    for extra in (
        {"score_buttons": [{"label": "", "delta": 1}]},
        {"score_buttons": [{"label": "+X", "delta": "не число"}]},
        {"warning_rules": [{"number": 1, "action": "unknown", "delta": 0}]},
    ):
        try:
            CategoryIn(**base, **extra)
        except ValueError:
            pass
        else:
            raise AssertionError("Некорректные правила категории прошли валидацию")


def test_category_schema_normalizes_name():
    model = CategoryIn(name="  Сабля  ")
    assert model.name == "Сабля"


def test_python_functions_and_classes_remain_reviewable():
    """Ограничивает размер отдельных функций и классов, а не только файлов."""

    oversized: list[str] = []
    for path in ROOT.glob("app/**/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.end_lineno is None:
                continue
            size = node.end_lineno - node.lineno + 1
            limit = 500 if isinstance(node, ast.ClassDef) else 150
            if size > limit:
                oversized.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.name}: {size}")

    assert not oversized, "Слишком крупные функции/классы:\n" + "\n".join(oversized)



def test_source_comments_are_written_in_russian():
    """Не позволяет возвращать англоязычные поясняющие комментарии в исходники."""

    comments: list[tuple[Path, int, str]] = []
    for path in ROOT.glob("app/**/*.py"):
        source = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments.append((path, token.start[0], token.string.lstrip("# ")))

    for path in ROOT.glob("app/static/*.js"):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("//"):
                comments.append((path, line_no, stripped[2:].strip()))

    css_comment = re.compile(r"/\*(.*?)\*/")
    for path in ROOT.glob("app/static/*.css"):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in css_comment.finditer(line):
                comments.append((path, line_no, match.group(1).strip()))

    non_russian = []
    for path, line_no, text in comments:
        if not re.search(r"[A-Za-zА-Яа-яЁё]", text):
            continue
        if not re.search(r"[А-Яа-яЁё]", text):
            non_russian.append(f"{path.relative_to(ROOT)}:{line_no}: {text}")

    assert not non_russian, "Комментарии без русского текста:\n" + "\n".join(non_russian)
