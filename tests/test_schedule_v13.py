"""Проверки управления площадками и раскрытия категорий участника в 1.3."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    Area,
    AuditEvent,
    Category,
    CategoryParticipant,
    CategoryTemplate,
    Match,
    MatchEvent,
    Participant,
    Tournament,
)


def reset_db() -> None:
    """Очищает тестовую БД с соблюдением внешних ключей."""

    init_db()
    with SessionLocal() as db:
        for model in [
            MatchEvent,
            AuditEvent,
            Match,
            Area,
            CategoryParticipant,
            Participant,
            Category,
            Tournament,
            CategoryTemplate,
        ]:
            db.execute(delete(model))
        db.commit()


def _scheduled_match(status: str = "ready") -> tuple[int, int, int]:
    """Создаёт турнир с одним назначенным боем и возвращает основные ID."""

    with SessionLocal() as db:
        tournament = Tournament(name="Площадки")
        db.add(tournament)
        db.flush()
        area = Area(tournament_id=tournament.id, name="Площадка 1")
        category = Category(tournament_id=tournament.id, name="Сабля", format="round_robin")
        db.add_all([area, category])
        db.flush()
        p1 = Participant(tournament_id=tournament.id, last_name="Первый")
        p2 = Participant(tournament_id=tournament.id, last_name="Второй")
        db.add_all([p1, p2])
        db.flush()
        cp1 = CategoryParticipant(category_id=category.id, participant_id=p1.id)
        cp2 = CategoryParticipant(category_id=category.id, participant_id=p2.id)
        db.add_all([cp1, cp2])
        db.flush()
        match = Match(
            category_id=category.id,
            stage="round_robin",
            match_no=1,
            red_cp_id=cp1.id,
            blue_cp_id=cp2.id,
            status=status,
            area_id=area.id,
            queue_order=1,
        )
        db.add(match)
        db.flush()
        area.current_match_id = match.id
        db.commit()
        return tournament.id, area.id, match.id


def test_reset_schedule_returns_unfinished_matches_to_unassigned() -> None:
    reset_db()
    tournament_id, area_id, match_id = _scheduled_match()

    with TestClient(app) as client:
        response = client.post(f"/api/tournaments/{tournament_id}/schedule-reset")

    assert response.status_code == 200, response.text
    assert response.json()["unassigned_matches"] == 1
    with SessionLocal() as db:
        match = db.get(Match, match_id)
        area = db.get(Area, area_id)
        assert match is not None and match.area_id is None and match.queue_order == 0
        assert area is not None and area.current_match_id is None


def test_reset_schedule_is_blocked_while_fight_is_in_progress() -> None:
    reset_db()
    tournament_id, _, match_id = _scheduled_match("in_progress")

    with TestClient(app) as client:
        response = client.post(f"/api/tournaments/{tournament_id}/schedule-reset")

    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.get(Match, match_id).area_id is not None


def test_delete_area_returns_future_matches_to_pool() -> None:
    reset_db()
    _, area_id, match_id = _scheduled_match()

    with TestClient(app) as client:
        response = client.delete(f"/api/areas/{area_id}")

    assert response.status_code == 200, response.text
    assert response.json()["returned_to_pool"] == 1
    with SessionLocal() as db:
        assert db.get(Area, area_id) is None
        match = db.get(Match, match_id)
        assert match is not None and match.area_id is None and match.queue_order == 0


def test_delete_area_is_blocked_during_active_fight() -> None:
    reset_db()
    _, area_id, _ = _scheduled_match("in_progress")

    with TestClient(app) as client:
        response = client.delete(f"/api/areas/{area_id}")

    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.get(Area, area_id) is not None


def test_participant_categories_endpoint_returns_groups_and_formats() -> None:
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Категории участника")
        db.add(tournament)
        db.flush()
        participant = Participant(tournament_id=tournament.id, last_name="Хомяк")
        sabre = Category(tournament_id=tournament.id, name="Сабля", format="groups")
        sword = Category(tournament_id=tournament.id, name="Длинный меч", format="knockout")
        db.add_all([participant, sabre, sword])
        db.flush()
        db.add_all([
            CategoryParticipant(category_id=sabre.id, participant_id=participant.id, group_name="B"),
            CategoryParticipant(category_id=sword.id, participant_id=participant.id),
        ])
        db.commit()
        participant_id = participant.id

    with TestClient(app) as client:
        response = client.get(f"/api/participants/{participant_id}/categories")

    assert response.status_code == 200, response.text
    rows = response.json()
    assert {row["name"] for row in rows} == {"Сабля", "Длинный меч"}
    sabre_row = next(row for row in rows if row["name"] == "Сабля")
    assert sabre_row["format"] == "groups"
    assert sabre_row["group_name"] == "B"


def test_schedule_columns_never_wrap_and_v13_controls_are_present() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "static"
    css = (root / "schedule.css").read_text(encoding="utf-8")
    schedule_js = (root / "schedule.js").read_text(encoding="utf-8")
    admin_js = (root / "admin.js").read_text(encoding="utf-8")

    assert "flex-wrap:nowrap" in css
    assert ".schedule-area-scroll" in css
    assert "resetScheduleAssignments" in schedule_js
    assert "data-delete-area" in schedule_js
    assert "quick-group-details" in schedule_js
    assert "data-participant-categories" in admin_js
