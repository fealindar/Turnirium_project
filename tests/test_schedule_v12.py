from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.engine import add_category_participant, generate_groups, generate_round_robin, start_group_stage
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


def reset_db():
    init_db()
    with SessionLocal() as db:
        for model in [MatchEvent, AuditEvent, Match, Area, CategoryParticipant, Participant, Category, Tournament, CategoryTemplate]:
            db.execute(delete(model))
        db.commit()


def test_round_robin_spreads_repeat_appearances_during_generation():
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Круговой")
        db.add(tournament); db.flush()
        db.add(Area(tournament_id=tournament.id, name="Площадка 1"))
        category = Category(tournament_id=tournament.id, name="Сабля", format="round_robin")
        db.add(category); db.flush()
        for index in range(5):
            participant = Participant(tournament_id=tournament.id, last_name=f"F{index + 1}")
            db.add(participant); db.flush(); add_category_participant(db, category.id, participant.id)
        db.commit()
        matches = sorted(generate_round_robin(db, category), key=lambda match: match.match_no)
        assert len(matches) == 10
        for previous, current in zip(matches, matches[1:]):
            previous_ids = {previous.red_cp_id, previous.blue_cp_id}
            current_ids = {current.red_cp_id, current.blue_cp_id}
            assert not previous_ids & current_ids


def test_schedule_marks_same_person_on_neighboring_positions_of_different_areas():
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Две площадки")
        db.add(tournament); db.flush()
        area1 = Area(tournament_id=tournament.id, name="Площадка 1")
        area2 = Area(tournament_id=tournament.id, name="Площадка 2")
        db.add_all([area1, area2]); db.flush()
        shared = Participant(tournament_id=tournament.id, last_name="Общий")
        p2 = Participant(tournament_id=tournament.id, last_name="A")
        p3 = Participant(tournament_id=tournament.id, last_name="B")
        db.add_all([shared, p2, p3]); db.flush()
        c1 = Category(tournament_id=tournament.id, name="Сабля", format="round_robin", status="ready")
        c2 = Category(tournament_id=tournament.id, name="Длинный меч", format="round_robin", status="ready")
        db.add_all([c1, c2]); db.flush()
        c1_shared = add_category_participant(db, c1.id, shared.id)
        c1_other = add_category_participant(db, c1.id, p2.id)
        c2_shared = add_category_participant(db, c2.id, shared.id)
        c2_other = add_category_participant(db, c2.id, p3.id)
        m1 = Match(category_id=c1.id, stage="round_robin", round_no=1, match_no=1, red_cp_id=c1_shared.id, blue_cp_id=c1_other.id, status="ready", area_id=area1.id, queue_order=10)
        m2 = Match(category_id=c2.id, stage="round_robin", round_no=1, match_no=1, red_cp_id=c2_shared.id, blue_cp_id=c2_other.id, status="ready", area_id=area2.id, queue_order=20)
        db.add_all([m1, m2]); db.commit()
        tournament_id = tournament.id

    with TestClient(app) as client:
        response = client.get(f"/api/tournaments/{tournament_id}/schedule")
        assert response.status_code == 200, response.text
        data = response.json()
        matches = [match for column in data["areas"] for match in column["matches"]]
        assert len(matches) == 2
        assert all(match["cross_area_warning"] for match in matches)
        assert all(match["cross_area_conflicts"] for match in matches)
        assert {match["queue_position"] for match in matches} == {1}
        assert {
            row["queue_position"]
            for match in matches
            for row in match["cross_area_conflicts"]
        } == {1}
        assert {row["area_name"] for match in matches for row in match["cross_area_conflicts"]} == {"Площадка 1", "Площадка 2"}


def test_quick_assignment_can_send_one_group_to_selected_area():
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Группы")
        db.add(tournament); db.flush()
        area1 = Area(tournament_id=tournament.id, name="Площадка 1")
        area2 = Area(tournament_id=tournament.id, name="Площадка 2")
        db.add_all([area1, area2])
        category = Category(tournament_id=tournament.id, name="Длинный меч", format="groups", group_target_size=4)
        db.add(category); db.flush()
        for index in range(8):
            participant = Participant(tournament_id=tournament.id, last_name=f"F{index + 1}")
            db.add(participant); db.flush(); add_category_participant(db, category.id, participant.id)
        db.commit()
        generate_groups(db, category)
        start_group_stage(db, category)
        tournament_id, category_id, area1_id = tournament.id, category.id, area1.id

    with TestClient(app) as client:
        schedule = client.get(f"/api/tournaments/{tournament_id}/schedule").json()
        unit = next(row for row in schedule["category_units"] if row["category_id"] == category_id)
        assert unit["participant_count"] == 8
        assert {group["name"] for group in unit["groups"]} == {"A", "B"}
        group_a = next(group for group in unit["groups"] if group["name"] == "A")
        assert group_a["ready_unassigned"] > 0

        assigned = client.post(
            f"/api/tournaments/{tournament_id}/schedule-assign-unit",
            json={"category_id": category_id, "area_id": area1_id, "group_name": "A"},
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["assigned"] == group_a["ready_unassigned"]

    with SessionLocal() as db:
        group_a_matches = db.scalars(select(Match).where(Match.category_id == category_id, Match.group_name == "A")).all()
        group_b_matches = db.scalars(select(Match).where(Match.category_id == category_id, Match.group_name == "B")).all()
        assert group_a_matches and all(match.area_id == area1_id for match in group_a_matches)
        assert group_b_matches and all(match.area_id is None for match in group_b_matches)


def test_secretary_and_public_static_assets_include_v12_controls():
    root = __import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "static"
    secretary = (root / "secretary.js").read_text(encoding="utf-8")
    public = (root / "public.js").read_text(encoding="utf-8")
    index = (root / "index.html").read_text(encoding="utf-8")
    assert 'id="toggleTimer"' in secretary
    assert 'id="startTimer"' not in secretary
    assert 'id="pauseTimer"' not in secretary
    assert "secretary-context-badge" in secretary
    assert "public-bracket-lines" in public
    assert "/static/schedule.js" in index
