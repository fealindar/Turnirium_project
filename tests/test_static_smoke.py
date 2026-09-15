from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_spa_routes_and_static_bundle_are_available():
    """Проверяет базовые веб-экраны и целостность подключённого frontend-набора."""

    index = (STATIC / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', index)
    assert refs, "index.html не содержит подключённых статических ресурсов"

    with TestClient(app) as client:
        for path in ("/admin", "/mat/1", "/board/1", "/public/1"):
            response = client.get(path)
            assert response.status_code == 200
            assert '<div id="app"></div>' in response.text

        for ref in refs:
            response = client.get(ref)
            assert response.status_code == 200, ref
            assert response.content, ref


def test_system_endpoint_reports_current_release():
    """Не позволяет случайно разойтись версии API и сборочного пакета."""

    with TestClient(app) as client:
        response = client.get("/api/system")
        assert response.status_code == 200
        assert response.json()["version"] == APP_VERSION == "1.1.0"
