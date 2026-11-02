"""Регрессии 1.2.0: выбор одной площадки и обычные/специальные исходы."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Match
from test_balance_and_mutual_results import seed_category


def _assigned_queue(category_id: int) -> list[tuple[int, str, int]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(Match).where(Match.category_id == category_id)
            .order_by(Match.queue_order, Match.id)
        ).all()
        return [(m.match_no, m.group_name or '', m.queue_order) for m in rows]


def test_single_selection_uses_original_assignment_semantics() -> None:
    """Один флажок в новом мультивыборе идентичен старой кнопке площадки."""
    tid, cid, (area_id,) = seed_category(area_count=1)
    with TestClient(app) as client:
        response = client.post(
            f'/api/tournaments/{tid}/schedule-assign-unit',
            json={'category_id': cid, 'area_id': area_id},
        )
        assert response.status_code == 200, response.text
        expected_count = response.json()['assigned']
        expected_queue = _assigned_queue(cid)

    tid, cid, (area_id,) = seed_category(area_count=1)
    with TestClient(app) as client:
        response = client.post(
            f'/api/tournaments/{tid}/schedule-assign-multi',
            json={'category_id': cid, 'area_ids': [area_id]},
        )
        assert response.status_code == 200, response.text
        assert response.json()['assigned'] == expected_count == 12
        assert response.json()['areas'] == {str(area_id): expected_count}
        assert _assigned_queue(cid) == expected_queue
        schedule = client.get(f'/api/tournaments/{tid}/schedule').json()
        assert not schedule['unassigned']


def test_single_selection_of_group_does_not_assign_other_group() -> None:
    tid, cid, (area_id,) = seed_category(area_count=1)
    with TestClient(app) as client:
        response = client.post(
            f'/api/tournaments/{tid}/schedule-assign-multi',
            json={'category_id': cid, 'group_name': 'A', 'area_ids': [area_id]},
        )
        assert response.status_code == 200, response.text
        assert response.json()['assigned'] == 6
        with SessionLocal() as db:
            matches = db.scalars(select(Match).where(Match.category_id == cid)).all()
            assert all(m.area_id == area_id for m in matches if m.group_name == 'A')
            assert all(m.area_id is None for m in matches if m.group_name == 'B')


def test_empty_and_duplicate_selections_are_rejected() -> None:
    tid, cid, (area_id,) = seed_category(area_count=1)
    with TestClient(app) as client:
        empty = client.post(f'/api/tournaments/{tid}/schedule-assign-multi',
                            json={'category_id': cid, 'area_ids': []})
        assert empty.status_code == 422
        duplicate = client.post(f'/api/tournaments/{tid}/schedule-assign-multi',
                                json={'category_id': cid, 'area_ids': [area_id, area_id]})
        assert duplicate.status_code == 400
        with SessionLocal() as db:
            assert not db.scalars(select(Match).where(Match.category_id == cid, Match.area_id.is_not(None))).all()


def test_finish_endpoint_accepts_immediate_points_or_draw() -> None:
    tid, cid, (area_id,) = seed_category(area_count=1)
    with SessionLocal() as db:
        matches = db.scalars(select(Match).where(Match.category_id == cid).order_by(Match.id)).all()
        red_win, draw_match = matches[:2]
        win_id, red_id, draw_id = red_win.id, red_win.red_cp_id, draw_match.id
    with TestClient(app) as client:
        win = client.post(f'/api/matches/{win_id}/finish',
                          json={'winner_cp_id': red_id, 'reason': 'POINTS'})
        assert win.status_code == 200, win.text
        assert win.json()['status'] == 'finished'
        draw = client.post(f'/api/matches/{draw_id}/finish',
                           json={'winner_cp_id': None, 'reason': 'DRAW'})
        assert draw.status_code == 200, draw.text
        assert draw.json()['status'] == 'finished'
        assert draw.json()['winner_cp_id'] is None
