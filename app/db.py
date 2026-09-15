from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    override = os.getenv("TOURNAMENT_DATA_DIR")
    root = Path(override).expanduser().resolve() if override else runtime_root() / "data"
    root.mkdir(parents=True, exist_ok=True)
    (root / "backups").mkdir(parents=True, exist_ok=True)
    return root


def default_db_path() -> Path:
    return data_dir() / "tournament.db"


def _selection_file() -> Path:
    return data_dir() / "database_selection.json"


def _load_selection() -> dict[str, Any]:
    try:
        raw = json.loads(_selection_file().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return {}


def _save_selection(active: Path, recent: list[str] | None = None) -> None:
    cfg = _load_selection()
    old_recent = cfg.get("recent_paths") if isinstance(cfg.get("recent_paths"), list) else []
    items = [str(active)] + list(recent or []) + [str(x) for x in old_recent]
    dedup: list[str] = []
    seen: set[str] = set()
    for value in items:
        try:
            normalized = str(Path(value).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            continue
        key = os.path.normcase(normalized)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(normalized)
        if len(dedup) >= 16:
            break
    payload = {"active_path": str(active), "recent_paths": dedup}
    target = _selection_file()
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def _validate_existing_database(path: Path) -> None:
    if not path.exists():
        raise ValueError("Файл базы данных не найден")
    if not path.is_file():
        raise ValueError("Выбранный путь не является файлом")
    if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise ValueError("Поддерживаются файлы SQLite: .db, .sqlite, .sqlite3")
    try:
        conn = sqlite3.connect(str(path), timeout=3)
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()
            if check and str(check[0]).lower() != "ok":
                raise ValueError(f"SQLite quick_check: {check[0]}")
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            }
        finally:
            conn.close()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Файл не является исправной SQLite БД: {exc}") from exc
    if tables and "tournaments" not in tables:
        raise ValueError("Это SQLite-файл другого приложения: таблицы Turnirium не найдены")


def _initial_database_path() -> Path:
    cfg = _load_selection()
    saved = cfg.get("active_path")
    if saved:
        try:
            path = Path(str(saved)).expanduser().resolve()
            _validate_existing_database(path)
            return path
        except (OSError, RuntimeError, ValueError):
            pass
    path = default_db_path().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    return path


def _make_engine(path: Path):
    eng = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()

    return eng


def _initialize_schema(bind) -> None:
    # Импорт регистрирует все модели в SQLAlchemy metadata перед create_all.
    from . import models as _models

    _ = _models
    Base.metadata.create_all(bind=bind)
    # Лёгкие миграции сохраняют совместимость существующих локальных БД без
    # отдельного фреймворка миграций, избыточного для небольшого настольного приложения.
    with bind.begin() as conn:
        inspector = inspect(conn)
        pcols = {c["name"] for c in inspector.get_columns("participants")}
        if "city" not in pcols:
            conn.execute(text("ALTER TABLE participants ADD COLUMN city VARCHAR(160) NOT NULL DEFAULT ''"))
        if "status" not in pcols:
            conn.execute(text("ALTER TABLE participants ADD COLUMN status VARCHAR(24) NOT NULL DEFAULT 'active'"))
            conn.execute(text("UPDATE participants SET status='withdrawn' WHERE active=0"))
        if "fee_paid" not in pcols:
            conn.execute(text("ALTER TABLE participants ADD COLUMN fee_paid BOOLEAN NOT NULL DEFAULT 0"))
        if "comment" not in pcols:
            conn.execute(text("ALTER TABLE participants ADD COLUMN comment TEXT NOT NULL DEFAULT ''"))

        tcols = {c["name"] for c in inspector.get_columns("tournaments")}
        if "status" not in tcols:
            conn.execute(text("ALTER TABLE tournaments ADD COLUMN status VARCHAR(24) NOT NULL DEFAULT 'active'"))
        if "completed_at" not in tcols:
            conn.execute(text("ALTER TABLE tournaments ADD COLUMN completed_at DATETIME"))
        if "avoid_consecutive_matches" not in tcols:
            conn.execute(text("ALTER TABLE tournaments ADD COLUMN avoid_consecutive_matches BOOLEAN NOT NULL DEFAULT 1"))
        if "preferred_match_gap" not in tcols:
            conn.execute(text("ALTER TABLE tournaments ADD COLUMN preferred_match_gap INTEGER NOT NULL DEFAULT 1"))

        ccols = {c["name"] for c in inspector.get_columns("categories")}
        if "completed_at" not in ccols:
            conn.execute(text("ALTER TABLE categories ADD COLUMN completed_at DATETIME"))
        if "win_points" not in ccols:
            conn.execute(text("ALTER TABLE categories ADD COLUMN win_points INTEGER NOT NULL DEFAULT 3"))
        if "draw_points" not in ccols:
            conn.execute(text("ALTER TABLE categories ADD COLUMN draw_points INTEGER NOT NULL DEFAULT 1"))

        if inspector.has_table("category_templates"):
            template_cols = {c["name"] for c in inspector.get_columns("category_templates")}
            if "win_points" not in template_cols:
                conn.execute(text("ALTER TABLE category_templates ADD COLUMN win_points INTEGER NOT NULL DEFAULT 3"))
            if "draw_points" not in template_cols:
                conn.execute(text("ALTER TABLE category_templates ADD COLUMN draw_points INTEGER NOT NULL DEFAULT 1"))

        mcols = {c["name"] for c in inspector.get_columns("matches")}
        if "is_third_place" not in mcols:
            conn.execute(text("ALTER TABLE matches ADD COLUMN is_third_place BOOLEAN NOT NULL DEFAULT 0"))


_DB_LOCK = threading.RLock()
_DB_PATH = _initial_database_path()
engine = _make_engine(_DB_PATH)
DB_PATH = _DB_PATH  # Снимок для обратной совместимости; внутренний код использует current_db_path().
DATABASE_URL = f"sqlite:///{_DB_PATH.as_posix()}"
_DB_GENERATION = 1
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def current_db_path() -> Path:
    with _DB_LOCK:
        return _DB_PATH


def current_db_generation() -> int:
    with _DB_LOCK:
        return _DB_GENERATION


def init_db() -> None:
    with _DB_LOCK:
        _initialize_schema(engine)


def switch_database(path: str | Path, *, remember: bool = True) -> Path:
    """Переключает новые сессии на выбранный SQLite-файл Turnirium."""
    global _DB_PATH, DB_PATH, DATABASE_URL, engine, _DB_GENERATION

    candidate = Path(path).expanduser().resolve()
    _validate_existing_database(candidate)
    with _DB_LOCK:
        if os.path.normcase(str(candidate)) == os.path.normcase(str(_DB_PATH)):
            if remember:
                _save_selection(candidate)
            return candidate

        new_engine = _make_engine(candidate)
        try:
            _initialize_schema(new_engine)
        except Exception:
            new_engine.dispose()
            raise

        old_engine = engine
        engine = new_engine
        _DB_PATH = candidate
        DB_PATH = candidate
        DATABASE_URL = f"sqlite:///{candidate.as_posix()}"
        _DB_GENERATION += 1
        SessionLocal.configure(bind=new_engine)
        if remember:
            _save_selection(candidate)
        old_engine.dispose()
    return candidate


def database_catalog() -> dict[str, Any]:
    """Возвращает известные приложению БД без автоматических резервных копий."""
    active = current_db_path()
    cfg = _load_selection()
    candidates: list[Path] = [default_db_path().resolve(), active]
    for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
        candidates.extend(data_dir().glob(pattern))
    for value in cfg.get("recent_paths", []) if isinstance(cfg.get("recent_paths"), list) else []:
        try:
            candidates.append(Path(str(value)).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            pass

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for path in candidates:
        key = os.path.normcase(str(path))
        if key in seen or not path.exists() or not path.is_file():
            continue
        seen.add(key)
        try:
            _validate_existing_database(path)
        except (OSError, RuntimeError, ValueError):
            continue
        stat = path.stat()
        rows.append({
            "name": path.name,
            "path": str(path),
            "active": key == os.path.normcase(str(active)),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "default": key == os.path.normcase(str(default_db_path().resolve())),
        })
    rows.sort(key=lambda row: (not row["active"], not row["default"], row["name"].lower()))
    return {"active_path": str(active), "databases": rows}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
