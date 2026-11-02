"""Регрессия зеркального табло площадки: 1.2.2."""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, _initialize_schema, _make_engine, init_db
from app.main import app
from app.models import Area, AuditEvent, Category, Match, Tournament
from test_secretary_flow import reset_db

ROOT = Path(__file__).resolve().parents[1]


def seed_areas():
    reset_db()
    with SessionLocal() as db:
        first_tournament = Tournament(name="Первый турнир")
        second_tournament = Tournament(name="Второй турнир")
        db.add_all((first_tournament, second_tournament))
        db.flush()
        areas = [
            Area(tournament_id=first_tournament.id, name="Площадка A"),
            Area(tournament_id=first_tournament.id, name="Площадка B"),
            Area(tournament_id=second_tournament.id, name="Площадка A"),
        ]
        db.add_all(areas)
        db.commit()
        return [a.id for a in areas]


def test_mirror_is_per_area_and_tournament_and_can_be_switched_repeatedly():
    a1, a2, a3 = seed_areas()
    with TestClient(app) as client:
        for a in (a1, a2, a3):
            state = client.get(f"/api/areas/{a}/state")
            assert state.status_code == 200
            assert state.json()["area"]["board_mirrored"] is False
            assert state.json()["current"] is None

        for value in (True, False, True):
            response = client.put(f"/api/areas/{a1}/board-mirror", json={"mirrored": value})
            assert response.status_code == 200, response.text
            assert response.json() == {"area_id": a1, "board_mirrored": value}
            assert client.get(f"/api/areas/{a1}/state").json()["area"]["board_mirrored"] is value

        for a in (a2, a3):
            assert client.get(f"/api/areas/{a}/state").json()["area"]["board_mirrored"] is False

        # Повторное сохранение того же значения допустимо и не создаёт лишний аудит.
        response = client.put(f"/api/areas/{a1}/board-mirror", json={"mirrored": True})
        assert response.status_code == 200

    # Состояние действительно хранится в SQLite, а не только в браузере.
    with SessionLocal() as db:
        assert db.get(Area, a1).board_mirrored is True
        assert db.get(Area, a2).board_mirrored is False
        assert db.get(Area, a3).board_mirrored is False
        audits = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "AREA_BOARD_MIRROR_CHANGED")).all()
        assert len(audits) == 3

    # Повторный запуск HTTP клиента — как обновление страницы/переподключение.
    with TestClient(app) as client:
        assert client.get(f"/api/areas/{a1}/state").json()["area"]["board_mirrored"] is True


def test_mirror_can_change_during_live_bout_without_modifying_match():
    a1, _, _ = seed_areas()
    with SessionLocal() as db:
        a = db.get(Area, a1)
        category = Category(tournament_id=a.tournament_id, name="Сабля", status="active")
        db.add(category)
        db.flush()
        match = Match(category_id=category.id, area_id=a1, status="in_progress",
                      red_score=9, blue_score=4, red_warnings=2, blue_warnings=1,
                      timer_running=False, remaining_ms=45000)
        db.add(match)
        db.flush()
        a.current_match_id = match.id
        db.commit()
        match_id = match.id

    with TestClient(app) as client:
        before = client.get(f"/api/areas/{a1}/state").json()["current"]
        assert before["status"] == "in_progress"
        assert client.put(f"/api/areas/{a1}/board-mirror", json={"mirrored": True}).status_code == 200
        after = client.get(f"/api/areas/{a1}/state").json()["current"]
        assert before == after
        assert client.put(f"/api/areas/{a1}/board-mirror", json={"mirrored": False}).status_code == 200
        assert client.get(f"/api/areas/{a1}/state").json()["current"] == before

    with SessionLocal() as db:
        m = db.get(Match, match_id)
        assert (m.red_score, m.blue_score, m.red_warnings, m.blue_warnings) == (9, 4, 2, 1)
        assert m.status == "in_progress"


def test_board_mirror_input_is_strict_and_missing_area_is_404():
    a1, _, _ = seed_areas()
    with TestClient(app) as client:
        for bad in ("true", 1, 0, None):
            assert client.put(f"/api/areas/{a1}/board-mirror", json={"mirrored": bad}).status_code == 422
        assert client.put(f"/api/areas/{a1}/board-mirror", json={}).status_code == 422
        assert client.put("/api/areas/999999/board-mirror", json={"mirrored": True}).status_code == 404
        assert client.get(f"/api/areas/{a1}/state").json()["area"]["board_mirrored"] is False


def test_board_is_notified_immediately_over_websocket():
    a1, _, _ = seed_areas()
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?screen=board&area_id={a1}") as ws:
            assert ws.receive_json()["type"] == "clients_changed"
            response = client.put(f"/api/areas/{a1}/board-mirror", json={"mirrored": True})
            assert response.status_code == 200
            event = ws.receive_json()
            assert event["type"] == "area_changed"
            assert event["area_id"] == a1
            assert event["board_mirrored"] is True


def test_old_database_gets_column_with_safe_default(tmp_path):
    path = tmp_path / "old_turnirium.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE areas (id INTEGER PRIMARY KEY, tournament_id INTEGER, name TEXT, enabled BOOLEAN, current_match_id INTEGER)")
    connection.execute("INSERT INTO areas (id,tournament_id,name,enabled) VALUES (7,1,'Старая площадка',1)")
    connection.commit()
    connection.close()

    engine = _make_engine(path)
    try:
        _initialize_schema(engine)
        _initialize_schema(engine)  # миграция идемпотентна
        connection = sqlite3.connect(path)
        try:
            row = connection.execute("SELECT board_mirrored FROM areas WHERE id=7").fetchone()
            assert row == (0,)
        finally:
            connection.close()
    finally:
        engine.dispose()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js не установлен")
def test_board_html_swaps_complete_sides_and_next_preview():
    """Исполняет настоящий board.js без браузера: проверяет порядок и данные."""
    script = r'''
const fs = require('fs');
const vm = require('vm');
let html='';
const el = {set innerHTML(value) {html=value;}, get innerHTML(){return html;}};
const ctx = {
  $:(sel)=>{if(sel==='#boardContent')return el;throw Error(sel)},
  esc:(value)=>String(value ?? ''),
  affiliation:(f)=>f?.club ?? '',
  fighterText:(f)=>f?.name ?? '—',
  fmtTime:(_)=>'00:45',
  stageName:(_)=>'Группа',
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('app/static/board.js','utf8'),ctx);
const state={
  area:{name:'Площадка 1',board_mirrored:false},
  current:{red:{name:'Red Fighter',club:'Club A'},blue:{name:'Blue Fighter',club:'Club B'},
    red_score:9,blue_score:4,red_warnings:2,blue_warnings:1,
    status:'in_progress',timer_running:true,category_name:'Test',stage:'group',remaining_ms:45000},
  next:{red:{name:'Next Red'},blue:{name:'Next Blue'},category_name:'Next'}
};
const check=(mirrored)=>{
  state.area.board_mirrored=mirrored;
  ctx.renderBoard(state);
  const sidePositions=['class="board-side red"','class="board-side blue"'].map(key=>html.indexOf(key));
  if(sidePositions.some(x=>x<0)) throw Error('Missing colored sides');
  if((sidePositions[0]>sidePositions[1])!==mirrored) throw Error('Wrong sides order');
  const red=html.match(/class="board-side red"[\s\S]*?<div class="board-score">(\d+)<\/div><div class="board-side-bottom">Предупреждения: <b>(\d+)<\/b>/);
  const blue=html.match(/class="board-side blue"[\s\S]*?<div class="board-score">(\d+)<\/div><div class="board-side-bottom">Предупреждения: <b>(\d+)<\/b>/);
  if(!red||red[1]!=='9'||red[2]!=='2'||!blue||blue[1]!=='4'||blue[2]!=='1')throw Error('Incorrect fighter data');
  const nr=html.indexOf('Next Red'), nb=html.indexOf('Next Blue');
  if((nr>nb)!==mirrored)throw Error('Wrong next preview order');
};
check(false);check(true);check(false);
state.current=null;
state.area.board_mirrored=true;
ctx.renderBoard(state);
if(html.indexOf('Next Blue')>html.indexOf('Next Red')) throw Error('Idle preview not mirrored');
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_toggle_is_always_in_secretary_topbar_not_in_fight_panel():
    js = (ROOT / "app/static/secretary.js").read_text(encoding="utf-8")
    assert 'Отзеркалить табло' in js
    assert 'id="boardMirrorToggle"' in js
    assert 'class="topbar secretary-topbar"' in js
    assert js.index('id="boardMirrorToggle"') < js.index('const load=async()=>')
