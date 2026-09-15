"""Проверки импорта участников и транзакционной смены статусов."""

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
    """Очищает тестовую БД в порядке, безопасном для внешних ключей."""

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


def test_participant_import_rejects_unknown_status() -> None:
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Импорт")
        db.add(tournament)
        db.commit()
        tournament_id = tournament.id

    content = "Фамилия;Имя;Клуб;Город;Статус\nИванов;Иван;Боевые Хомяки;;ожидает\n"
    with TestClient(app) as client:
        response = client.post(
            f"/api/tournaments/{tournament_id}/participants/import",
            json={"filename": "participants.csv", "content": content},
        )

    assert response.status_code == 400
    assert "Неизвестный статус" in response.json()["detail"]


def test_participant_import_rolls_back_when_withdrawal_hits_active_match() -> None:
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Транзакционный импорт")
        db.add(tournament)
        db.flush()
        category = Category(tournament_id=tournament.id, name="Сабля", format="groups")
        db.add(category)
        db.flush()

        active = Participant(
            tournament_id=tournament.id,
            last_name="Активный",
            first_name="Боец",
            club="Боевые Хомяки",
        )
        opponent = Participant(tournament_id=tournament.id, last_name="Соперник")
        db.add_all([active, opponent])
        db.flush()
        active_link = CategoryParticipant(category_id=category.id, participant_id=active.id)
        opponent_link = CategoryParticipant(category_id=category.id, participant_id=opponent.id)
        db.add_all([active_link, opponent_link])
        db.flush()
        db.add(
            Match(
                category_id=category.id,
                stage="group",
                match_no=1,
                red_cp_id=active_link.id,
                blue_cp_id=opponent_link.id,
                status="in_progress",
            )
        )
        db.commit()
        tournament_id = tournament.id
        active_id = active.id

    content = (
        "Фамилия;Имя;Клуб;Город;Статус\n"
        "Новый;Участник;;;active\n"
        "Активный;Боец;Боевые Хомяки;;withdrawn\n"
    )
    with TestClient(app) as client:
        response = client.post(
            f"/api/tournaments/{tournament_id}/participants/import",
            json={"filename": "participants.csv", "content": content},
        )

    assert response.status_code == 409
    assert "активном поединке" in response.json()["detail"]

    with SessionLocal() as db:
        active = db.get(Participant, active_id)
        assert active is not None
        assert active.status == "active"
        assert active.active is True
        assert db.scalar(select(Participant).where(Participant.last_name == "Новый")) is None


def test_new_tournament_keeps_product_defaults() -> None:
    reset_db()
    with TestClient(app) as client:
        created = client.post("/api/tournaments", json={})
        assert created.status_code == 200, created.text
        tournament_id = created.json()["id"]

        tournament = client.get(f"/api/tournaments/{tournament_id}")
        areas = client.get(f"/api/tournaments/{tournament_id}/areas")

    assert tournament.status_code == 200
    assert tournament.json()["name"] == "Новый Турнир"
    assert areas.status_code == 200
    assert [area["name"] for area in areas.json()] == ["Площадка 1"]


def test_participant_import_rejects_fields_longer_than_storage_limits() -> None:
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Пределы импорта")
        db.add(tournament)
        db.commit()
        tournament_id = tournament.id

    content = (
        "Фамилия;Имя;Клуб;Город;Статус\n"
        f"{'Я' * 101};Иван;;;active\n"
    )
    with TestClient(app) as client:
        response = client.post(
            f"/api/tournaments/{tournament_id}/participants/import",
            json={"filename": "participants.csv", "content": content},
        )

    assert response.status_code == 400
    assert "Строка 2" in response.json()["detail"]
