from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.engine import add_category_participant, finish_match, generate_groups, start_group_stage
from app.main import app
from app.models import Area, AuditEvent, Category, CategoryParticipant, CategoryTemplate, Match, MatchEvent, Participant, Tournament


def reset_db():
    init_db()
    with SessionLocal() as db:
        for model in [MatchEvent, AuditEvent, Match, Area, CategoryParticipant, Participant, Category, Tournament, CategoryTemplate]:
            db.execute(delete(model))
        db.commit()


def make_group_queue():
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Secretary flow")
        db.add(tournament)
        db.flush()
        area = Area(tournament_id=tournament.id, name="Площадка 1")
        db.add(area)
        category = Category(tournament_id=tournament.id, name="Сабля", format="groups", group_target_size=4)
        db.add(category)
        db.flush()
        for idx in range(4):
            participant = Participant(tournament_id=tournament.id, last_name=f"F{idx + 1}")
            db.add(participant)
            db.flush()
            add_category_participant(db, category.id, participant.id)
        db.commit()
        generate_groups(db, category)
        start_group_stage(db, category)
        db.refresh(area)
        assert area.current_match_id is not None
        current_id = area.current_match_id
        queued_ids = db.scalars(
            select(Match.id).where(
                Match.area_id == area.id,
                Match.status.in_(["ready", "pending"]),
                Match.id != current_id,
            ).order_by(Match.queue_order, Match.id)
        ).all()
        assert queued_ids
        return area.id, current_id, queued_ids[0]


def test_secretary_cannot_advance_until_current_result_is_saved():
    area_id, current_id, expected_next_id = make_group_queue()

    with TestClient(app) as client:
        blocked = client.post(f"/api/areas/{area_id}/next")
        assert blocked.status_code == 409
        assert "внесите результат" in blocked.json()["detail"].lower()

    with SessionLocal() as db:
        current = db.get(Match, current_id)
        finish_match(db, current, current.red_cp_id, "POINTS")

    with TestClient(app) as client:
        advanced = client.post(f"/api/areas/{area_id}/next")
        assert advanced.status_code == 200, advanced.text
        assert advanced.json()["id"] == expected_next_id

        state = client.get(f"/api/areas/{area_id}/state")
        assert state.status_code == 200
        assert state.json()["current"]["id"] == expected_next_id


def test_direct_select_cannot_bypass_unfinished_current_match():
    area_id, current_id, next_id = make_group_queue()

    with TestClient(app) as client:
        blocked = client.post(f"/api/areas/{area_id}/select/{next_id}")
        assert blocked.status_code == 409
        assert "результат текущего боя" in blocked.json()["detail"].lower()

    with SessionLocal() as db:
        current = db.get(Match, current_id)
        finish_match(db, current, current.red_cp_id, "POINTS")

    with TestClient(app) as client:
        selected = client.post(f"/api/areas/{area_id}/select/{next_id}")
        assert selected.status_code == 200, selected.text
        assert selected.json()["id"] == next_id


def test_moving_selected_not_started_match_clears_old_area_current_reference():
    area_id, current_id, _ = make_group_queue()

    with SessionLocal() as db:
        tournament_id = db.get(Area, area_id).tournament_id
        second = Area(tournament_id=tournament_id, name="Площадка 2")
        db.add(second)
        db.commit()
        second_id = second.id

    with TestClient(app) as client:
        moved = client.post(
            "/api/schedule/assign",
            json={"match_id": current_id, "area_id": second_id},
        )
        assert moved.status_code == 200, moved.text

    with SessionLocal() as db:
        first = db.get(Area, area_id)
        match = db.get(Match, current_id)
        assert first.current_match_id is None
        assert match.area_id == second_id
