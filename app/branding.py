from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_BRANDING = {
    "app_name": "Turnirium",
    "developer_club_name": "",
    "developer_club_url": "",
    "show_footer_branding": True,
}


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bundled_path() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "branding.json"
        return p if p.exists() else None
    p = Path(__file__).resolve().parents[1] / "branding.json"
    return p if p.exists() else None


def load_branding() -> dict:
    data = dict(DEFAULT_BRANDING)
    # Соседний branding.json имеет приоритет, поэтому уже собранный EXE можно
    # перебрендировать без изменения БД и повторной сборки.
    candidates = [_project_root() / "branding.json", _bundled_path()]
    seen: set[Path] = set()
    for path in candidates:
        if not path or path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                data.update({k: payload[k] for k in DEFAULT_BRANDING if k in payload})
                break
        except Exception:
            continue
    data["app_name"] = str(data.get("app_name") or DEFAULT_BRANDING["app_name"]).strip()
    data["developer_club_name"] = str(data.get("developer_club_name") or "").strip()
    data["developer_club_url"] = str(data.get("developer_club_url") or "").strip()
    data["show_footer_branding"] = bool(data.get("show_footer_branding", True))
    return data
