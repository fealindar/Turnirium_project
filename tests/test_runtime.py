from fastapi.testclient import TestClient

from app.main import app


def test_runtime_endpoint_lists_interfaces_and_clients():
    with TestClient(app) as client:
        r = client.get('/api/system/runtime')
        assert r.status_code == 200
        data = r.json()
        assert data['version'] == '1.1.4'
        assert 'interfaces' in data and isinstance(data['interfaces'], list)
        assert data['client_count'] == 0


def test_websocket_registers_screen_metadata_and_disconnects_cleanly():
    with TestClient(app) as client:
        with client.websocket_connect('/ws?screen=secretary&area_id=7') as ws:
            # После регистрации ожидается начальное уведомление.
            event = ws.receive_json()
            assert event['type'] == 'clients_changed'
            data = client.get('/api/system/runtime').json()
            assert data['client_count'] == 1
            row = data['clients'][0]
            assert row['screen'] == 'secretary'
            assert row['area_id'] == 7
            assert row['ip']
        data = client.get('/api/system/runtime').json()
        assert data['client_count'] == 0


def test_database_can_be_switched_and_restored_without_restart(tmp_path):
    import sqlite3

    from app.db import current_db_path

    original = current_db_path()
    alternate = tmp_path / 'alternate_turnirium.db'
    sqlite3.connect(alternate).close()
    try:
        with TestClient(app) as client:
            r = client.post('/api/databases/select', json={'path': str(alternate)})
            assert r.status_code == 200, r.text
            assert r.json()['db_path'] == str(alternate.resolve())

            system = client.get('/api/system').json()
            assert system['db_path'] == str(alternate.resolve())

            catalog = client.get('/api/databases').json()
            assert catalog['active_path'] == str(alternate.resolve())
            assert any(row['active'] and row['path'] == str(alternate.resolve()) for row in catalog['databases'])

            # Схема инициализируется в выбранном пустом SQLite-файле.
            conn = sqlite3.connect(alternate)
            try:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
            assert {'tournaments', 'categories', 'matches'} <= tables
    finally:
        with TestClient(app) as client:
            restored = client.post('/api/databases/select', json={'path': str(original)})
            assert restored.status_code == 200, restored.text


def test_database_selector_rejects_unrelated_sqlite_file(tmp_path):
    import sqlite3

    unrelated = tmp_path / 'other_app.db'
    conn = sqlite3.connect(unrelated)
    try:
        conn.execute('CREATE TABLE something_else (id INTEGER PRIMARY KEY)')
        conn.commit()
    finally:
        conn.close()
    with TestClient(app) as client:
        r = client.post('/api/databases/select', json={'path': str(unrelated)})
        assert r.status_code == 400
        assert 'Turnirium' in r.json()['detail']


def test_backup_endpoint_creates_consistent_sqlite_copy():
    """Резервная копия не должна падать из-за отсутствующего datetime и должна создавать файл."""
    from pathlib import Path

    with TestClient(app) as client:
        response = client.post('/api/backup')
        assert response.status_code == 200, response.text
        backup_path = Path(response.json()['path'])
        assert backup_path.exists()
        assert backup_path.stat().st_size > 0
        backup_path.unlink(missing_ok=True)
