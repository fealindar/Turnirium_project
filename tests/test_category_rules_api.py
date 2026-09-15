from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.engine import add_category_participant, generate_groups, generate_round_robin, start_group_stage
from app.main import app
from app.models import Area, AuditEvent, Category, CategoryParticipant, CategoryTemplate, Match, MatchEvent, Participant, Tournament


def reset_db():
    init_db()
    with SessionLocal() as db:
        for model in [MatchEvent, AuditEvent, Match, Area, CategoryParticipant, Participant, Category, Tournament, CategoryTemplate]:
            db.execute(delete(model))
        db.commit()


def category_payload(c: Category, **changes):
    data = {
        "name": c.name,
        "format": c.format,
        "match_duration_sec": c.match_duration_sec,
        "timer_warning_sec": c.timer_warning_sec,
        "score_buttons": [{"label": "+1", "delta": 1}, {"label": "-1", "delta": -1}],
        "warning_rules": [
            {"number": 1, "action": "warning", "delta": 0},
            {"number": 2, "action": "score_penalty", "delta": -2},
            {"number": 3, "action": "forfeit", "delta": 0},
        ],
        "cumulative_warning_limit": c.cumulative_warning_limit,
        "group_target_size": c.group_target_size,
        "group_qualifiers": c.group_qualifiers,
        "swiss_rounds": c.swiss_rounds,
        "win_points": c.win_points,
        "draw_points": c.draw_points,
    }
    data.update(changes)
    return data


def make_group_category():
    reset_db()
    with SessionLocal() as db:
        t = Tournament(name="Rules test")
        db.add(t); db.flush()
        db.add(Area(tournament_id=t.id, name="Площадка 1"))
        c = Category(tournament_id=t.id, name="До 70 кг", format="groups", group_target_size=4)
        db.add(c); db.flush()
        for i in range(4):
            p = Participant(tournament_id=t.id, last_name=f"P{i+1}")
            db.add(p); db.flush(); add_category_participant(db, c.id, p.id)
        db.commit()
        return c.id


def test_rules_can_change_after_stage_start_until_first_real_bout_then_lock():
    cid = make_group_category()
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generate_groups(db, c)
        start_group_stage(db, c)
        assert c.bracket_locked is True
        payload = category_payload(c, format="round_robin", win_points=3, draw_points=1)

    with TestClient(app) as client:
        r = client.put(f"/api/categories/{cid}", json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["format"] == "round_robin"
        assert r.json()["win_points"] == 3

    with SessionLocal() as db:
        c = db.get(Category, cid)
        assert db.scalar(select(Match.id).where(Match.category_id == cid)) is None
        rows = generate_round_robin(db, c)
        rows[0].status = "in_progress"
        db.commit()
        payload = category_payload(c, win_points=5)

    with TestClient(app) as client:
        r = client.put(f"/api/categories/{cid}", json=payload)
        assert r.status_code == 409
        assert "первого поединка" in r.json()["detail"]


def test_template_can_be_saved_directly_from_entered_rule_values():
    reset_db()
    payload = {
        "name": "Круговая 3-1",
        "format": "round_robin",
        "match_duration_sec": 90,
        "timer_warning_sec": 7,
        "score_buttons": [{"label": "+2", "delta": 2}],
        "warning_rules": [{"number": 1, "action": "warning", "delta": 0}],
        "cumulative_warning_limit": 3,
        "group_target_size": 4,
        "group_qualifiers": 2,
        "swiss_rounds": 4,
        "win_points": 3,
        "draw_points": 1,
    }
    with TestClient(app) as client:
        r = client.post("/api/category-templates", json=payload)
        assert r.status_code == 200, r.text
        saved = r.json()
        assert saved["name"] == "Круговая 3-1"
        assert saved["format"] == "round_robin"
        assert saved["win_points"] == 3 and saved["draw_points"] == 1
        rows = client.get("/api/category-templates").json()
        assert any(x["name"] == "Круговая 3-1" for x in rows)


def test_new_category_uses_fencing_friendly_default_scoring():
    reset_db()
    with SessionLocal() as db:
        t = Tournament(name="Fencing defaults")
        db.add(t); db.commit(); tournament_id = t.id
    with TestClient(app) as client:
        r = client.post(f"/api/tournaments/{tournament_id}/categories", json={"name": "Сабля женская"})
        assert r.status_code == 200, r.text
        saved = r.json()
        assert saved["score_buttons"] == [
            {"label": "-1", "delta": -1},
            {"label": "+1", "delta": 1},
            {"label": "+2", "delta": 2},
            {"label": "+3", "delta": 3},
        ]
        assert saved["win_points"] == 3
        assert saved["draw_points"] == 1


def test_name_can_change_after_start_when_legacy_json_differs_only_by_formatting():
    reset_db()
    with SessionLocal() as db:
        tournament = Tournament(name="Legacy JSON")
        db.add(tournament)
        db.flush()
        category = Category(
            tournament_id=tournament.id,
            name="Старое название",
            format="round_robin",
            score_buttons_json='[{"label":"+1","delta":1},{"label":"-1","delta":-1}]',
            warning_rules_json='[{"number":1,"action":"warning","delta":0},{"number":2,"action":"score_penalty","delta":-2},{"number":3,"action":"forfeit","delta":0}]',
        )
        db.add(category)
        db.flush()
        for index in range(2):
            participant = Participant(tournament_id=tournament.id, last_name=f"L{index + 1}")
            db.add(participant)
            db.flush()
            add_category_participant(db, category.id, participant.id)
        db.commit()
        rows = generate_round_robin(db, category)
        rows[0].status = "in_progress"
        db.commit()
        payload = category_payload(category, name="Новое название", format="round_robin")
        category_id = category.id

    with TestClient(app) as client:
        response = client.put(f"/api/categories/{category_id}", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Новое название"


def test_seed_api_rejects_duplicate_category_participants():
    category_id = make_group_category()
    with TestClient(app) as client:
        participants = client.get(f"/api/categories/{category_id}/participants").json()
        first_id = participants[0]["id"]
        response = client.put(
            f"/api/categories/{category_id}/seed",
            json={"cp_ids": [first_id, first_id]},
        )
        assert response.status_code == 400
        assert "повтор" in response.json()["detail"].lower()
