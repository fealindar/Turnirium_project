"""Регрессии 1.1.7: баланс нескольких площадок и обоюдные исходы."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.engine import (
    add_category_participant, finish_match, generate_groups, generate_knockout,
    generate_round_robin, start_group_stage,
)
from app.main import app
from app.models import (
    Area, AuditEvent, Category, CategoryParticipant, CategoryTemplate,
    Match, MatchEvent, Participant, Tournament,
)


def seed_category(fmt: str = "groups", count: int = 8, area_count: int = 2):
    init_db()
    with SessionLocal() as db:
        for model in (MatchEvent, AuditEvent, Match, Area, CategoryParticipant,
                      Participant, Category, Tournament, CategoryTemplate):
            db.execute(delete(model))
        tournament = Tournament(name="Проверка баланса")
        db.add(tournament)
        db.flush()
        areas = [Area(tournament_id=tournament.id, name=f"Площадка {i}")
                 for i in range(1, area_count + 1)]
        db.add_all(areas)
        category = Category(tournament_id=tournament.id, name="Категория", format=fmt,
                            group_target_size=4)
        db.add(category)
        db.flush()
        for i in range(count):
            participant = Participant(tournament_id=tournament.id, last_name=f"Боец {i + 1}")
            db.add(participant)
            db.flush()
            add_category_participant(db, category.id, participant.id)
        if fmt == "groups":
            generate_groups(db, category)
            start_group_stage(db, category)
        elif fmt == "round_robin":
            generate_round_robin(db, category)
        elif fmt == "knockout":
            generate_knockout(db, category)
        db.commit()
        return tournament.id, category.id, [area.id for area in areas]


def test_multi_assign_twelve_fights_six_per_area():
    tid, cid, area_ids = seed_category()
    with TestClient(app) as client:
        response = client.post(f"/api/tournaments/{tid}/schedule-assign-multi",
                               json={"category_id": cid, "area_ids": area_ids})
        assert response.status_code == 200, response.text
        assert response.json()["areas"] == {str(a): 6 for a in area_ids}
        schedule = client.get(f"/api/tournaments/{tid}/schedule").json()
        assert [len(row["matches"]) for row in schedule["areas"]] == [6, 6]
        assert not schedule["unassigned"]


def test_global_optimize_balances_ten_two_while_preserving_current_fight():
    tid, cid, area_ids = seed_category()
    with SessionLocal() as db:
        matches = db.scalars(select(Match).where(Match.category_id == cid)
                             .order_by(Match.id)).all()
        assert len(matches) == 12
        for index, match in enumerate(matches):
            match.area_id = area_ids[0] if index < 10 else area_ids[1]
            match.queue_order = index + 1
        fixed = matches[0]
        fixed.status = "in_progress"
        fixed.red_score = 3
        db.get(Area, area_ids[0]).current_match_id = fixed.id
        db.get(Tournament, tid).avoid_consecutive_matches = False
        db.commit()
        fixed_id = fixed.id
    with TestClient(app) as client:
        response = client.post(f"/api/tournaments/{tid}/schedule-optimize")
        assert response.status_code == 200, response.text
        result = response.json()
        assert sorted(result["area_loads"].values()) == [6, 6]
        assert result["moved_matches"] >= 4
        assert result["unavoidable_conflicts"] == 0
        with SessionLocal() as db:
            match = db.get(Match, fixed_id)
            assert (match.area_id, match.status, match.red_score) == (area_ids[0], "in_progress", 3)
            assert db.get(Area, area_ids[0]).current_match_id == fixed_id
            assert len(db.scalars(select(Match).where(Match.area_id == area_ids[0])).all()) == 6
            assert len(db.scalars(select(Match).where(Match.area_id == area_ids[1])).all()) == 6


def test_optimize_does_not_assign_unassigned_or_move_disabled_area():
    tid, cid, area_ids = seed_category(area_count=3)
    with SessionLocal() as db:
        matches = db.scalars(select(Match).where(Match.category_id == cid)
                             .order_by(Match.id)).all()
        for index, match in enumerate(matches[:10]):
            match.area_id = area_ids[0] if index < 8 else area_ids[1]
            match.queue_order = index + 1
        db.get(Area, area_ids[2]).enabled = False
        db.commit()
        unassigned_ids = {match.id for match in matches[10:]}
    with TestClient(app) as client:
        response = client.post(f"/api/tournaments/{tid}/schedule-optimize")
        assert response.status_code == 200, response.text
        assert sorted(response.json()["area_loads"].values()) == [5, 5]
        with SessionLocal() as db:
            assert all(db.get(Match, mid).area_id is None for mid in unassigned_ids)
            assert not db.scalars(select(Match).where(Match.area_id == area_ids[2])).all()


def test_optimization_puts_ready_before_unresolved_pending_bouts():
    tid, cid, area_ids = seed_category()
    with SessionLocal() as db:
        matches = db.scalars(select(Match).where(Match.category_id == cid)
                             .order_by(Match.id)).all()
        for index, match in enumerate(matches):
            match.area_id = area_ids[index % 2]
            match.queue_order = index + 1
        # Имитируем ещё не готовый слот; его нельзя ставить впереди готовых боёв.
        pending = matches[0]
        pending.status = "pending"
        pending_id = pending.id
        db.commit()
    with TestClient(app) as client:
        result = client.post(f"/api/tournaments/{tid}/schedule-optimize")
        assert result.status_code == 200, result.text
    with SessionLocal() as db:
        match = db.get(Match, pending_id)
        others = db.scalars(select(Match).where(
            Match.area_id == match.area_id, Match.id != pending_id,
            Match.status == "ready",
        )).all()
        assert others
        assert all(other.queue_order < match.queue_order for other in others)


def test_mutual_warning_and_technical_finals_and_scores_count_as_two_losses():
    tid, cid, _ = seed_category(fmt="round_robin", count=2)
    with SessionLocal() as db:
        match = db.scalar(select(Match).where(Match.category_id == cid))
        match.red_score, match.blue_score = 7, 5
        match_id = match.id
        db.commit()
    with TestClient(app) as client:
        for side in ("red", "blue"):
            r = client.post(f"/api/matches/{match_id}/technical-loss", json={"side": side})
            assert r.status_code == 200, r.text
        r = client.post(f"/api/matches/{match_id}/finish",
                        json={"winner_cp_id": None, "reason": "DOUBLE_TECHNICAL_LOSS"})
        assert r.status_code == 200, r.text
        assert r.json()["winner_cp_id"] is None
        assert r.json()["reason"] == "DOUBLE_TECHNICAL_LOSS"
        rows = client.get(f"/api/categories/{cid}/standings").json()
        assert all(row["played"] == 1 and row["losses"] == 1 and
                   row["wins"] == 0 and row["draws"] == 0 and row["points"] == 0 for row in rows)
        assert sorted((row["for"], row["against"]) for row in rows) == [(5, 7), (7, 5)]

        for reason in ("DOUBLE_FORFEIT", "DOUBLE_WARNING_FORFEIT", "DOUBLE_DISQUALIFICATION", "DOUBLE_WITHDRAWAL"):
            corrected = client.put(f"/api/matches/{match_id}/correction", json={
                "red_score": 8, "blue_score": 6, "red_warnings": 0, "blue_warnings": 0,
                "winner_cp_id": None, "reason": reason,
            })
            assert corrected.status_code == 200, corrected.text
            assert corrected.json()["match"]["reason"] == reason
            standings = client.get(f"/api/categories/{cid}/standings").json()
            assert all(row["losses"] == 1 and row["wins"] == 0 and row["points"] == 0 for row in standings)
            assert sorted((row["for"], row["against"]) for row in standings) == [(6, 8), (8, 6)]


def test_mutual_loss_keeps_elimination_scores_on_result_correction():
    tid, cid, _ = seed_category(fmt="knockout", count=2)
    with SessionLocal() as db:
        match = db.scalar(select(Match).where(Match.category_id == cid))
        match.red_score, match.blue_score = 11, 9
        finish_match(db, match, match.red_cp_id, "POINTS")
        mid = match.id
    with TestClient(app) as client:
        corrected = client.put(f"/api/matches/{mid}/correction", json={
            "red_score": 11, "blue_score": 9, "red_warnings": 0, "blue_warnings": 0,
            "winner_cp_id": None, "reason": "DOUBLE_DISQUALIFICATION",
        })
        assert corrected.status_code == 200, corrected.text
        results = client.get(f"/api/categories/{cid}/standings").json()
        assert all(row["played"] == 1 and row["losses"] == 1 and row["wins"] == 0
                   for row in results)
        assert sorted((row["for"], row["against"]) for row in results) == [(9, 11), (11, 9)]
        assert all(row["last_result"] == "DOUBLE_DISQUALIFICATION" for row in results)
