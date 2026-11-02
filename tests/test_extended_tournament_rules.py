"""Регрессии: квалификация, площадки, санкции, Swiss и досрочное завершение."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.engine import (
    add_category_participant, finish_match, generate_group_playoff,
    generate_groups, generate_knockout, generate_swiss_round,
    start_group_stage, start_swiss_round, standings,
)
from app.main import app
from app.models import (
    Area, AuditEvent, Category, CategoryParticipant, CategoryTemplate,
    Match, MatchEvent, Participant, Tournament,
)
from app.routes.schemas import CategoryIn


def _seed(fmt="groups", count=4, areas=1, **rules):
    init_db()
    with SessionLocal() as db:
        for model in (MatchEvent, AuditEvent, Match, Area, CategoryParticipant,
                      Participant, Category, Tournament, CategoryTemplate):
            db.execute(delete(model))
        t = Tournament(name="Расширенные сценарии")
        db.add(t)
        db.flush()
        a = [Area(tournament_id=t.id, name=f"Площадка {i}") for i in range(1, areas + 1)]
        db.add_all(a)
        c = Category(tournament_id=t.id, name="Категория", format=fmt, **rules)
        db.add(c)
        db.flush()
        for i in range(count):
            p = Participant(tournament_id=t.id, last_name=f"Участник{i + 1}")
            db.add(p)
            db.flush()
            add_category_participant(db, c.id, p.id)
        db.commit()
        return t.id, c.id, [area.id for area in a]


def test_full_group_qualifiers_create_full_playoff():
    data = CategoryIn(name="Группа", format="groups", group_target_size=4, group_qualifiers=4)
    assert data.group_qualifiers == data.group_target_size
    tid, cid, areas = _seed(count=8, group_target_size=4, group_qualifiers=4)
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generate_groups(db, c)
        start_group_stage(db, c)
        for match in db.scalars(select(Match).where(Match.category_id == cid)).all():
            finish_match(db, match, match.red_cp_id)
        playoffs = generate_group_playoff(db, c)
        assert len([m for m in playoffs if m.round_no == 1]) == 4
        qualifying = {pid for m in playoffs if m.round_no == 1 for pid in (m.red_cp_id, m.blue_cp_id)}
        assert len(qualifying) == 8


def test_single_area_never_assigns_without_explicit_action():
    tid, cid, (area_id,) = _seed()
    with SessionLocal() as db:
        category = db.get(Category, cid)
        generate_groups(db, category)
        start_group_stage(db, category)
    with TestClient(app) as client:
        first = client.get(f"/api/tournaments/{tid}/schedule").json()
        second = client.get(f"/api/tournaments/{tid}/schedule").json()
        assert first["unassigned"] and second["unassigned"]
        assert all(m["area_id"] is None for m in second["unassigned"])
        assert not first["areas"][0]["matches"]
        assign = client.post(f"/api/tournaments/{tid}/schedule-assign-unit",
                             json={"category_id": cid, "area_id": area_id})
        assert assign.status_code == 200, assign.text
        assert assign.json()["assigned"] == len(first["unassigned"])


def test_multi_area_assignment_balances_and_does_not_move_other_groups():
    tid, cid, area_ids = _seed(count=8, areas=3, group_target_size=4)
    with SessionLocal() as db:
        category = db.get(Category, cid)
        generate_groups(db, category)
        start_group_stage(db, category)
    with TestClient(app) as client:
        invalid = client.post(f"/api/tournaments/{tid}/schedule-assign-multi",
                              json={"category_id":cid, "area_ids":[area_ids[0], area_ids[0]]})
        assert invalid.status_code == 400
        assigned = client.post(f"/api/tournaments/{tid}/schedule-assign-multi",
                               json={"category_id":cid, "group_name":"A", "area_ids":area_ids})
        assert assigned.status_code == 200, assigned.text
        result=assigned.json()
        assert result["assigned"] == 6
        assert len(result["areas"]) >= 2
        with SessionLocal() as db:
            ms = db.scalars(select(Match).where(Match.category_id == cid)).all()
            assert len({m.id for m in ms}) == len(ms)
            assert {m.area_id for m in ms if m.group_name == 'A'} <= set(area_ids)
            assert all(m.area_id is None for m in ms if m.group_name == 'B')


def test_technical_defeat_can_be_marked_on_both_and_needs_final_confirmation():
    tid, cid, _ = _seed(fmt="round_robin", count=2)
    with SessionLocal() as db:
        from app.engine import generate_round_robin
        generate_round_robin(db, db.get(Category, cid))
        mid = db.scalar(select(Match.id).where(Match.category_id == cid))
    with TestClient(app) as client:
        red = client.post(f"/api/matches/{mid}/technical-loss",json={"side":"red"})
        assert red.status_code == 200, red.text
        assert red.json()["pending_penalties"] == {"red":"TECHNICAL_LOSS"}
        blue = client.post(f"/api/matches/{mid}/technical-loss",json={"side":"blue"})
        assert blue.status_code == 200, blue.text
        assert blue.json()["pending_penalties"] == {"red":"TECHNICAL_LOSS", "blue":"TECHNICAL_LOSS"}
        assert blue.json()["status"] == "ready"
        wrong = client.post(f"/api/matches/{mid}/finish",json={"reason":"POINTS", "winner_cp_id":blue.json()["blue"]["cp_id"]})
        assert wrong.status_code == 409
        finish = client.post(f"/api/matches/{mid}/finish",json={"reason":"DOUBLE_FORFEIT", "winner_cp_id":None})
        assert finish.status_code == 200, finish.text
        assert finish.json()["winner_cp_id"] is None and finish.json()["status"] == "finished"
        rows = client.get(f"/api/categories/{cid}/standings").json()
        assert all(r["losses"] == 1 and r["wins"] == 0 for r in rows)


def test_warning_forfeit_on_both_sides_does_not_finish_automatically():
    tid, cid, _ = _seed(fmt="round_robin", count=2, warning_rules_json='[{"number":1,"action":"forfeit","delta":0}]',
                         cumulative_warning_limit=0)
    with SessionLocal() as db:
        from app.engine import generate_round_robin
        generate_round_robin(db, db.get(Category, cid))
        mid = db.scalar(select(Match.id).where(Match.category_id == cid))
    with TestClient(app) as client:
        for side in ("red","blue"):
            r = client.post(f"/api/matches/{mid}/warning", json={"side":side})
            assert r.status_code == 200, r.text
            assert r.json()["match"]["status"] == "ready"
        penalties = client.get(f"/api/matches/{mid}").json()["pending_penalties"]
        assert penalties == {"red":"WARNING_FORFEIT", "blue":"WARNING_FORFEIT"}
        final=client.post(f"/api/matches/{mid}/finish", json={"winner_cp_id":None, "reason":"DOUBLE_FORFEIT"})
        assert final.status_code == 200, final.text


def test_technical_defeat_can_be_retracted_before_finishing():
    tid, cid, _ = _seed(fmt="knockout", count=2)
    with SessionLocal() as db:
        generate_knockout(db,db.get(Category,cid))
        mid=db.scalar(select(Match.id).where(Match.category_id==cid))
    with TestClient(app) as client:
        assert client.post(f"/api/matches/{mid}/technical-loss",json={"side":"red"}).status_code==200
        again=client.post(f"/api/matches/{mid}/technical-loss",json={"side":"red"})
        assert again.status_code==200 and not again.json()["pending_penalties"]
        winner=again.json()["red"]["cp_id"]
        assert client.post(f"/api/matches/{mid}/finish",json={"winner_cp_id":winner, "reason":"POINTS"}).status_code==200


def test_double_elimination_propagates_empty_slot_to_final():
    tid, cid, _ = _seed(fmt="knockout", count=4)
    with SessionLocal() as db:
        category=db.get(Category,cid)
        generate_knockout(db,category)
        semis=db.scalars(select(Match).where(Match.category_id==cid,Match.round_no==1)).all()
        for side in ('red','blue'):
            from app.services.match_penalties import toggle_technical_loss
            toggle_technical_loss(db,semis[0],side)
        finish_match(db,semis[0],None,'DOUBLE_FORFEIT')
        final=db.scalar(select(Match).where(Match.category_id==cid, Match.round_no==2,Match.is_third_place.is_(False)))
        assert final.status=='blocked'
        finish_match(db,semis[1],semis[1].red_cp_id)
        db.refresh(final)
        assert final.status=='finished' and final.result_reason=='BYE'
        assert final.winner_cp_id == semis[1].red_cp_id


def test_extra_swiss_round_does_not_reset_past_results():
    tid, cid, _ = _seed(fmt="swiss", count=4, swiss_rounds=1)
    with SessionLocal() as db:
        category=db.get(Category,cid)
        first=generate_swiss_round(db,category)
        start_swiss_round(db,category)
        finished_id=first[0].id
        finish_match(db,first[0],first[0].red_cp_id)
        with TestClient(app) as client:
            extra=client.post(f"/api/categories/{cid}/swiss-add-round")
            assert extra.status_code==200,extra.text
            assert extra.json()["swiss_rounds"]==2
            for m in first[1:]:
                finish_match(db,m,m.red_cp_id)
            next_round=client.post(f"/api/categories/{cid}/swiss-next")
            assert next_round.status_code==200,next_round.text
            assert next_round.json()["round"]==2
            old=db.get(Match,finished_id)
            assert old.status=='finished' and old.winner_cp_id == first[0].red_cp_id


def test_early_completion_excludes_active_and_unplayed_scores_and_can_reopen():
    tid, cid, (area_id,) = _seed(fmt='round_robin', count=4)
    with SessionLocal() as db:
        from app.engine import generate_round_robin
        category=db.get(Category,cid)
        rows=generate_round_robin(db,category)
        first=rows[0]
        first.red_score=5
        first.blue_score=1
        db.flush()
        finish_match(db, first, first.red_cp_id)
        expected_winner=first.red_cp_id
        partial=rows[1]
        partial.red_score=99
        partial.status='in_progress'
        db.commit()
        partial_id=partial.id
    with TestClient(app) as client:
        denied=client.post(f'/api/categories/{cid}/complete')
        assert denied.status_code==409
        done=client.post(f'/api/categories/{cid}/complete',json={'cancel_unfinished':True})
        assert done.status_code==200,done.text
        assert done.json()['cancelled_matches']==5
        rank=client.get(f'/api/categories/{cid}/standings').json()
        winrow=next(row for row in rank if row['cp_id']==expected_winner)
        assert winrow['wins']==1 and winrow['for']==5
        assert all(r['for'] < 90 for r in rank)
        with SessionLocal() as db:
            assert db.get(Match, partial_id).status=='cancelled'
        reopened=client.post(f'/api/categories/{cid}/reopen')
        assert reopened.status_code==200,reopened.text
        with SessionLocal() as db:
            assert db.get(Match, partial_id).status=='ready'
