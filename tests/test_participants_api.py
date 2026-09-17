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


def test_participant_organizational_details_are_persisted() -> None:
    """Оплата и комментарий хранятся отдельно от спортивного статуса участника."""

    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Взносы")
        db.add(tournament)
        db.flush()
        participant = Participant(tournament_id=tournament.id, last_name="Хомяк")
        db.add(participant)
        db.commit()
        participant_id = participant.id
        tournament_id = tournament.id

    with TestClient(app) as client:
        response = client.put(
            f"/api/participants/{participant_id}/details",
            json={"fee_paid": True, "comment": "Оплата наличными у организатора"},
        )
        listed = client.get(f"/api/tournaments/{tournament_id}/participants")

    assert response.status_code == 200, response.text
    assert response.json()["fee_paid"] is True
    assert response.json()["comment"] == "Оплата наличными у организатора"
    row = listed.json()[0]
    assert row["fee_paid"] is True
    assert row["comment"] == "Оплата наличными у организатора"


def test_legacy_participant_import_does_not_clear_payment_and_comment() -> None:
    """Старый CSV без новых колонок не должен стирать организационные данные."""

    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Совместимость импорта")
        db.add(tournament)
        db.flush()
        participant = Participant(
            tournament_id=tournament.id,
            last_name="Иванов",
            first_name="Иван",
            club="Боевые Хомяки",
            fee_paid=True,
            comment="Сохраняемая заметка",
        )
        db.add(participant)
        db.commit()
        tournament_id = tournament.id
        participant_id = participant.id

    content = "Фамилия;Имя;Клуб;Город;Статус\nИванов;Иван;Боевые Хомяки;;active\n"
    with TestClient(app) as client:
        response = client.post(
            f"/api/tournaments/{tournament_id}/participants/import",
            json={"filename": "old.csv", "content": content},
        )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        participant = db.get(Participant, participant_id)
        assert participant is not None
        assert participant.fee_paid is True
        assert participant.comment == "Сохраняемая заметка"


def test_category_participant_can_be_removed_before_first_fight_and_resets_prepared_matches() -> None:
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Исключение до старта")
        db.add(tournament)
        db.flush()
        category = Category(tournament_id=tournament.id, name="Сабля", format="knockout", status="ready")
        db.add(category)
        db.flush()
        first = Participant(tournament_id=tournament.id, last_name="Первый")
        second = Participant(tournament_id=tournament.id, last_name="Второй")
        db.add_all([first, second])
        db.flush()
        first_link = CategoryParticipant(category_id=category.id, participant_id=first.id, seed_order=1)
        second_link = CategoryParticipant(category_id=category.id, participant_id=second.id, seed_order=2)
        db.add_all([first_link, second_link])
        db.flush()
        db.add(
            Match(
                category_id=category.id,
                stage="knockout",
                round_no=1,
                match_no=1,
                red_cp_id=first_link.id,
                blue_cp_id=second_link.id,
                status="ready",
            )
        )
        db.commit()
        category_id = category.id
        first_id = first.id

    with TestClient(app) as client:
        response = client.delete(f"/api/categories/{category_id}/participants/{first_id}")

    assert response.status_code == 200, response.text
    assert response.json()["bracket_reset"] is True
    with SessionLocal() as db:
        assert db.scalar(
            select(CategoryParticipant).where(
                CategoryParticipant.category_id == category_id,
                CategoryParticipant.participant_id == first_id,
            )
        ) is None
        assert db.scalar(select(Match).where(Match.category_id == category_id)) is None
        category = db.get(Category, category_id)
        assert category is not None
        assert category.status == "draft"
        assert db.get(Participant, first_id) is not None


def test_category_participant_removal_is_blocked_after_real_fight_started() -> None:
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Исключение после старта")
        db.add(tournament)
        db.flush()
        category = Category(tournament_id=tournament.id, name="Меч", format="round_robin", status="ready")
        db.add(category)
        db.flush()
        first = Participant(tournament_id=tournament.id, last_name="Первый")
        second = Participant(tournament_id=tournament.id, last_name="Второй")
        db.add_all([first, second])
        db.flush()
        first_link = CategoryParticipant(category_id=category.id, participant_id=first.id, seed_order=1)
        second_link = CategoryParticipant(category_id=category.id, participant_id=second.id, seed_order=2)
        db.add_all([first_link, second_link])
        db.flush()
        db.add(
            Match(
                category_id=category.id,
                stage="round_robin",
                round_no=1,
                match_no=1,
                red_cp_id=first_link.id,
                blue_cp_id=second_link.id,
                status="in_progress",
            )
        )
        db.commit()
        category_id = category.id
        first_id = first.id

    with TestClient(app) as client:
        response = client.delete(f"/api/categories/{category_id}/participants/{first_id}")

    assert response.status_code == 409
    assert "после начала" in response.json()["detail"].lower()
    with SessionLocal() as db:
        assert db.scalar(
            select(CategoryParticipant).where(
                CategoryParticipant.category_id == category_id,
                CategoryParticipant.participant_id == first_id,
            )
        ) is not None


def test_participant_card_reports_category_removal_availability() -> None:
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Карточка участника")
        db.add(tournament)
        db.flush()
        open_category = Category(tournament_id=tournament.id, name="До старта", format="knockout")
        started_category = Category(tournament_id=tournament.id, name="После старта", format="knockout", status="ready")
        db.add_all([open_category, started_category])
        db.flush()
        participant = Participant(tournament_id=tournament.id, last_name="Боец")
        opponent = Participant(tournament_id=tournament.id, last_name="Соперник")
        db.add_all([participant, opponent])
        db.flush()
        open_link = CategoryParticipant(category_id=open_category.id, participant_id=participant.id)
        started_link = CategoryParticipant(category_id=started_category.id, participant_id=participant.id)
        opponent_link = CategoryParticipant(category_id=started_category.id, participant_id=opponent.id)
        db.add_all([open_link, started_link, opponent_link])
        db.flush()
        db.add(
            Match(
                category_id=started_category.id,
                stage="knockout",
                round_no=1,
                match_no=1,
                red_cp_id=started_link.id,
                blue_cp_id=opponent_link.id,
                status="finished",
                result_reason="POINTS",
            )
        )
        db.commit()
        participant_id = participant.id

    with TestClient(app) as client:
        response = client.get(f"/api/participants/{participant_id}/categories")

    assert response.status_code == 200, response.text
    by_name = {row["name"]: row for row in response.json()}
    assert by_name["До старта"]["can_remove"] is True
    assert by_name["После старта"]["can_remove"] is False
