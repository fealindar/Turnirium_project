import json

from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.engine import add_category_participant, add_warning, clear_tournament_data, correct_finished_match, finish_match, generate_group_playoff, generate_groups, generate_round_robin, generate_knockout, generate_swiss_round, rebuild_bracket_stage_from_slots, rebuild_groups_from_assignments, rebuild_swiss_round_from_slots, standings, start_group_stage, start_swiss_round, withdraw_participant
from app.exporter import write_json_export, write_pdf_export
from app.models import Area, AuditEvent, Category, CategoryParticipant, CategoryTemplate, Match, MatchEvent, Participant, Tournament


def reset_db():
    init_db()
    with SessionLocal() as db:
        for model in [MatchEvent, AuditEvent, Match, Area, CategoryParticipant, Participant, Category, Tournament, CategoryTemplate]:
            db.execute(delete(model))
        db.commit()


def create_category(fmt="knockout", n=5, **kwargs):
    reset_db()
    with SessionLocal() as db:
        t = Tournament(name="Test")
        db.add(t); db.flush()
        db.add(Area(tournament_id=t.id, name="Площадка 1"))
        c = Category(tournament_id=t.id, name="Категория", format=fmt, **kwargs)
        db.add(c); db.flush()
        for i in range(n):
            p = Participant(tournament_id=t.id, last_name=f"P{i+1}")
            db.add(p); db.flush(); add_category_participant(db, c.id, p.id)
        db.commit()
        return c.id


def test_knockout_byes_never_create_dead_empty_branch():
    cid = create_category("knockout", 5)
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generate_knockout(db, c)
        first = db.scalars(select(Match).where(Match.category_id == cid, Match.round_no == 1).order_by(Match.match_no)).all()
        assert len(first) == 4
        assert all(m.red_cp_id or m.blue_cp_id for m in first)
        assert sum(m.result_reason == "BYE" for m in first) == 3
        second = db.scalars(select(Match).where(Match.category_id == cid, Match.round_no == 2)).all()
        assert any(m.status == "ready" for m in second)


def test_warning_penalty_and_forfeit():
    cid = create_category("knockout", 2)
    with SessionLocal() as db:
        c = db.get(Category, cid); generate_knockout(db, c)
        m = db.scalar(select(Match).where(Match.category_id == cid, Match.status == "ready"))
        red_id, blue_id = m.red_cp_id, m.blue_cp_id
        add_warning(db, m, "red")
        m = db.get(Match, m.id); assert m.red_warnings == 1 and m.red_score == 0
        add_warning(db, m, "red")
        m = db.get(Match, m.id); assert m.red_warnings == 2 and m.red_score == -2
        add_warning(db, m, "red")
        m = db.get(Match, m.id); assert m.status == "finished" and m.winner_cp_id == blue_id


def test_groups_create_playoff_after_all_group_matches_finished():
    cid = create_category("groups", 8, group_target_size=4, group_qualifiers=2)
    with SessionLocal() as db:
        c = db.get(Category, cid); generate_groups(db, c); start_group_stage(db, c)
        group_matches = db.scalars(select(Match).where(Match.category_id == cid, Match.stage == "group")).all()
        assert group_matches
        for m in group_matches:
            finish_match(db, m, m.red_cp_id)
        c = db.get(Category, cid)
        playoff = generate_group_playoff(db, c)
        assert playoff
        assert all(m.stage == "playoff" for m in playoff)


def test_swiss_next_round_avoids_repeats_when_possible():
    cid = create_category("swiss", 6, swiss_rounds=3)
    with SessionLocal() as db:
        c = db.get(Category, cid); r1 = generate_swiss_round(db, c); start_swiss_round(db, c)
        pairs1 = {frozenset((m.red_cp_id, m.blue_cp_id)) for m in r1 if m.blue_cp_id}
        for m in r1:
            if m.blue_cp_id: finish_match(db, m, m.red_cp_id)
        c = db.get(Category, cid); r2 = generate_swiss_round(db, c)
        pairs2 = {frozenset((m.red_cp_id, m.blue_cp_id)) for m in r2 if m.blue_cp_id}
        assert not (pairs1 & pairs2)


def test_group_draw_separates_same_club_when_possible_and_auto_assigns_single_area():
    reset_db()
    with SessionLocal() as db:
        t = Tournament(name="Spread")
        db.add(t); db.flush()
        area = Area(tournament_id=t.id, name="Площадка 1")
        db.add(area)
        c = Category(tournament_id=t.id, name="Groups", format="groups", group_target_size=4)
        db.add(c); db.flush()
        clubs = ["A", "A", "B", "B", "C", "C", "D", "D"]
        cities = ["X", "X", "Y", "Y", "Z", "Z", "Q", "Q"]
        for i, (club, city) in enumerate(zip(clubs, cities), 1):
            p = Participant(tournament_id=t.id, last_name=f"P{i}", club=club, city=city)
            db.add(p); db.flush(); add_category_participant(db, c.id, p.id)
        db.commit()
        generate_groups(db, c)
        cps = db.scalars(select(CategoryParticipant).where(CategoryParticipant.category_id == c.id)).all()
        by_group = {}
        for cp in cps:
            by_group.setdefault(cp.group_name, []).append(cp)
        assert len(by_group) == 2
        for members in by_group.values():
            member_clubs = [cp.participant.club for cp in members]
            assert len(member_clubs) == len(set(member_clubs))
        matches = db.scalars(select(Match).where(Match.category_id == c.id)).all()
        assert matches and all(m.status == "staged" and m.area_id is None for m in matches)
        start_group_stage(db, c)
        matches = db.scalars(select(Match).where(Match.category_id == c.id)).all()
        assert all(m.area_id == area.id for m in matches)
        assert db.get(Area, area.id).current_match_id is not None


def test_manual_group_move_rebuilds_unstarted_group_matches():
    cid = create_category("groups", 6, group_target_size=3)
    with SessionLocal() as db:
        c = db.get(Category, cid); generate_groups(db, c)
        cps = db.scalars(select(CategoryParticipant).where(CategoryParticipant.category_id == cid).order_by(CategoryParticipant.id)).all()
        layout = {"A": [cps[0].id, cps[1].id], "B": [cp.id for cp in cps[2:]]}
        rebuild_groups_from_assignments(db, c, layout)
        rows = db.scalars(select(CategoryParticipant).where(CategoryParticipant.category_id == cid)).all()
        assert {cp.id for cp in rows if cp.group_name == "A"} == set(layout["A"])
        assert {cp.id for cp in rows if cp.group_name == "B"} == set(layout["B"])


def test_knockout_draw_separates_same_club_in_first_round_when_possible():
    reset_db()
    with SessionLocal() as db:
        t = Tournament(name="KO")
        db.add(t); db.flush(); db.add(Area(tournament_id=t.id, name="Площадка 1"))
        c = Category(tournament_id=t.id, name="KO", format="knockout")
        db.add(c); db.flush()
        for i, club in enumerate(["A", "A", "B", "B"], 1):
            p = Participant(tournament_id=t.id, last_name=f"P{i}", club=club, city="City")
            db.add(p); db.flush(); add_category_participant(db, c.id, p.id)
        db.commit(); generate_knockout(db, c)
        first = db.scalars(select(Match).where(Match.category_id == c.id, Match.round_no == 1).order_by(Match.match_no)).all()
        assert all(m.red_cp.participant.club != m.blue_cp.participant.club for m in first)


def test_manual_knockout_slot_swap_rebuilds_tree_before_start():
    cid = create_category("knockout", 4)
    with SessionLocal() as db:
        c = db.get(Category, cid); generate_knockout(db, c)
        first = db.scalars(select(Match).where(Match.category_id == cid, Match.round_no == 1).order_by(Match.match_no)).all()
        slots = [v for m in first for v in (m.red_cp_id, m.blue_cp_id)]
        slots[0], slots[-1] = slots[-1], slots[0]
        rebuild_bracket_stage_from_slots(db, c, "knockout", slots)
        updated = db.scalars(select(Match).where(Match.category_id == cid, Match.round_no == 1).order_by(Match.match_no)).all()
        assert [v for m in updated for v in (m.red_cp_id, m.blue_cp_id)] == slots


def test_withdrawn_participant_gets_status_and_future_match_walkover():
    cid = create_category("knockout", 4)
    with SessionLocal() as db:
        c = db.get(Category, cid); generate_knockout(db, c)
        first = db.scalars(select(Match).where(Match.category_id == cid, Match.round_no == 1).order_by(Match.match_no)).all()
        target = first[0]
        withdrawn_cp = target.red_cp
        opponent = target.blue_cp_id
        participant = withdrawn_cp.participant
        withdraw_participant(db, participant)
        db.refresh(participant); db.refresh(target)
        assert participant.status == "withdrawn" and participant.active is False
        assert target.status == "finished" and target.winner_cp_id == opponent
        assert target.result_reason == "WITHDRAWAL"


def test_clear_database_can_preserve_category_templates():
    reset_db()
    with SessionLocal() as db:
        t = Tournament(name="Keep template"); db.add(t); db.flush()
        db.add(Area(tournament_id=t.id, name="Площадка 1"))
        db.add(CategoryTemplate(name="Правила взрослых", format="knockout"))
        db.add(Participant(tournament_id=t.id, last_name="Иванов")); db.commit()
        clear_tournament_data(db, preserve_templates=True)
        assert db.scalar(select(Tournament)) is None
        assert db.scalar(select(Participant)) is None
        assert db.scalar(select(CategoryTemplate).where(CategoryTemplate.name == "Правила взрослых")) is not None


def test_technical_loss_reason_is_preserved():
    cid = create_category("knockout", 2)
    with SessionLocal() as db:
        c = db.get(Category, cid); generate_knockout(db, c)
        m = db.scalar(select(Match).where(Match.category_id == cid, Match.status == "ready"))
        finish_match(db, m, m.blue_cp_id, "TECHNICAL_LOSS")
        db.refresh(m)
        assert m.status == "finished"
        assert m.result_reason == "TECHNICAL_LOSS"


def test_category_exports_pdf_and_versioned_json():
    cid = create_category("knockout", 2)
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generate_knockout(db, c)
        m = db.scalar(select(Match).where(Match.category_id == cid, Match.status == "ready"))
        finish_match(db, m, m.red_cp_id, "POINTS")
        json_path = write_json_export(db, c)
        pdf_path = write_pdf_export(db, c)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == "1.3"
        assert payload["category"]["id"] == cid
        assert payload["matches"][0]["reason"] == "POINTS"
        assert pdf_path.read_bytes().startswith(b"%PDF-")


def test_knockout_creates_third_place_and_fills_semifinal_losers():
    cid = create_category("knockout", 4)
    with SessionLocal() as db:
        c = db.get(Category, cid); generate_knockout(db, c)
        semis = db.scalars(select(Match).where(Match.category_id == cid, Match.stage == "knockout", Match.round_no == 1, Match.is_third_place.is_(False)).order_by(Match.match_no)).all()
        bronze = db.scalar(select(Match).where(Match.category_id == cid, Match.is_third_place.is_(True)))
        assert bronze is not None and bronze.status == "blocked"
        losers=[]
        for m in semis:
            losers.append(m.blue_cp_id)
            finish_match(db, m, m.red_cp_id)
        db.refresh(bronze)
        final = db.scalar(select(Match).where(
            Match.category_id == cid, Match.stage == "knockout",
            Match.round_no == 2, Match.is_third_place.is_(False),
        ))
        assert {bronze.red_cp_id, bronze.blue_cp_id} == set(losers)
        assert bronze.status == "ready"
        assert final is not None and bronze.match_no < final.match_no
        assert bronze.area_id == final.area_id
        assert bronze.queue_order < final.queue_order


def test_group_composition_remains_editable_after_stage_start_until_fighter_has_bout():
    cid = create_category("groups", 6, group_target_size=3)
    with SessionLocal() as db:
        c=db.get(Category,cid);generate_groups(db,c)
        cps=db.scalars(select(CategoryParticipant).where(CategoryParticipant.category_id==cid).order_by(CategoryParticipant.id)).all()
        rebuild_groups_from_assignments(db,c,{"A":[cps[0].id,cps[1].id,cps[2].id],"B":[cps[3].id,cps[4].id,cps[5].id]})
        start_group_stage(db,c)
        # Реального боя ещё не было: бойца можно переносить между группами.
        rebuild_groups_from_assignments(db,c,{"A":[cps[0].id,cps[1].id],"B":[cps[2].id,cps[3].id,cps[4].id,cps[5].id]})
        db.refresh(cps[2])
        assert cps[2].group_name == "B"


def test_group_fighter_locks_after_first_real_bout_but_unplayed_fighters_can_still_move():
    cid = create_category("groups", 6, group_target_size=3)
    with SessionLocal() as db:
        c=db.get(Category,cid);generate_groups(db,c)
        cps=db.scalars(select(CategoryParticipant).where(CategoryParticipant.category_id==cid).order_by(CategoryParticipant.id)).all()
        rebuild_groups_from_assignments(db,c,{"A":[cps[0].id,cps[1].id,cps[2].id],"B":[cps[3].id,cps[4].id,cps[5].id]})
        start_group_stage(db,c)
        first=db.scalar(select(Match).where(Match.category_id==cid,Match.stage=="group",Match.group_name=="A").order_by(Match.match_no))
        finish_match(db,first,first.red_cp_id)
        locked=first.red_cp_id
        unlocked=next(cp.id for cp in cps[:3] if cp.id not in {first.red_cp_id,first.blue_cp_id})
        try:
            rebuild_groups_from_assignments(db,c,{"A":[cp.id for cp in cps[:3] if cp.id!=locked],"B":[locked]+[cp.id for cp in cps[3:]]})
            assert False, "fighter with a completed bout must be locked to the group"
        except ValueError:
            pass
        rebuild_groups_from_assignments(db,c,{"A":[cp.id for cp in cps[:3] if cp.id!=unlocked],"B":[unlocked]+[cp.id for cp in cps[3:]]})
        moved=db.get(CategoryParticipant,unlocked)
        assert moved.group_name == "B"


def test_swiss_current_round_can_be_rearranged_before_start():
    cid=create_category("swiss",5,swiss_rounds=2)
    with SessionLocal() as db:
        c=db.get(Category,cid);rows=generate_swiss_round(db,c)
        slots=[v for m in rows for v in (m.red_cp_id,m.blue_cp_id)]
        nonempty=[i for i,v in enumerate(slots) if v]
        a,b=nonempty[0],nonempty[-1];slots[a],slots[b]=slots[b],slots[a]
        rebuild_swiss_round_from_slots(db,c,slots)
        updated=db.scalars(select(Match).where(Match.category_id==cid,Match.stage=="swiss",Match.round_no==1).order_by(Match.match_no)).all()
        assert [v for m in updated for v in (m.red_cp_id,m.blue_cp_id)] == slots
        start_swiss_round(db,c)
        assert all(m.status in {"ready","finished"} for m in updated)


def test_round_robin_generates_every_pair_once_and_supports_draws():
    cid=create_category("round_robin",4,win_points=3,draw_points=1)
    with SessionLocal() as db:
        c=db.get(Category,cid);rows=generate_round_robin(db,c)
        assert len(rows)==6
        pairs={frozenset((m.red_cp_id,m.blue_cp_id)) for m in rows}
        assert len(pairs)==6 and all(m.stage=="round_robin" and m.status=="ready" for m in rows)
        finish_match(db,rows[0],None,"DRAW")
        from app.engine import standings
        table=standings(db,cid,round_robin_only=True)
        played=[r for r in table if r["played"]]
        assert len(played)==2 and all(r["draws"]==1 and r["points"]==1 for r in played)


def test_swiss_unstarted_pairs_can_be_rearranged_after_round_start_but_started_pair_is_locked():
    cid=create_category("swiss",6,swiss_rounds=2)
    with SessionLocal() as db:
        c=db.get(Category,cid);rows=generate_swiss_round(db,c);start_swiss_round(db,c)
        rows=db.scalars(select(Match).where(Match.category_id==cid,Match.stage=="swiss",Match.round_no==1).order_by(Match.match_no)).all()
        slots=[v for m in rows for v in (m.red_cp_id,m.blue_cp_id)]
        slots[2],slots[4]=slots[4],slots[2]
        rebuild_swiss_round_from_slots(db,c,slots)
        updated=db.scalars(select(Match).where(Match.category_id==cid,Match.stage=="swiss",Match.round_no==1).order_by(Match.match_no)).all()
        assert [v for m in updated for v in (m.red_cp_id,m.blue_cp_id)]==slots
        finish_match(db,updated[0],updated[0].red_cp_id)
        locked_slots=[v for m in updated for v in (m.red_cp_id,m.blue_cp_id)]
        locked_slots[0],locked_slots[2]=locked_slots[2],locked_slots[0]
        try:
            rebuild_swiss_round_from_slots(db,c,locked_slots)
            assert False, "started Swiss pair must stay fixed"
        except ValueError:
            pass


def test_group_standings_use_configurable_win_and_draw_points():
    cid = create_category("groups", 4, group_target_size=4, win_points=3, draw_points=1)
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generate_groups(db, c)
        start_group_stage(db, c)
        matches = db.scalars(select(Match).where(Match.category_id == cid, Match.stage == "group").order_by(Match.match_no)).all()
        draw = matches[0]
        finish_match(db, draw, None, "DRAW")
        win = next(m for m in matches[1:] if m.status != "finished")
        finish_match(db, win, win.red_cp_id, "POINTS")
        from app.engine import standings
        rows = standings(db, cid, draw.group_name)
        by_id = {r["cp_id"]: r for r in rows}
        assert by_id[draw.red_cp_id]["draws"] == 1
        assert by_id[draw.red_cp_id]["points"] >= 1
        assert by_id[draw.blue_cp_id]["draws"] == 1
        assert by_id[draw.blue_cp_id]["points"] >= 1
        assert by_id[win.red_cp_id]["points"] >= 3


def test_draw_is_rejected_for_knockout():
    cid = create_category("knockout", 2)
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generate_knockout(db, c)
        m = db.scalar(select(Match).where(Match.category_id == cid, Match.status == "ready"))
        try:
            finish_match(db, m, None, "DRAW")
            assert False, "draw must not be allowed in knockout"
        except ValueError:
            pass



def test_completed_group_match_can_be_corrected_and_standings_recalculate():
    cid = create_category("groups", 4, group_target_size=4, win_points=3, draw_points=1)
    with SessionLocal() as db:
        from app.engine import standings
        c = db.get(Category, cid)
        generate_groups(db, c); start_group_stage(db, c)
        m = db.scalar(select(Match).where(Match.category_id == cid, Match.stage == "group", Match.status == "ready"))
        red, blue = m.red_cp_id, m.blue_cp_id
        m.red_score = 2; m.blue_score = 1
        finish_match(db, m, red, "POINTS")
        m = db.get(Match, m.id)
        correct_finished_match(db, m, red_score=1, blue_score=3, red_warnings=0, blue_warnings=0, winner_cp_id=blue, reason="POINTS")
        rows = {r["cp_id"]: r for r in standings(db, cid, m.group_name)}
        assert rows[blue]["wins"] == 1 and rows[blue]["points"] == 3
        assert rows[red]["wins"] == 0
        assert db.get(Match, m.id).blue_score == 3


def test_knockout_correction_repropagates_final_and_bronze_before_they_start():
    cid = create_category("knockout", 4)
    with SessionLocal() as db:
        c = db.get(Category, cid); generate_knockout(db, c)
        semis = db.scalars(select(Match).where(Match.category_id == cid, Match.stage == "knockout", Match.round_no == 1, Match.is_third_place.is_(False)).order_by(Match.match_no)).all()
        first_red, first_blue = semis[0].red_cp_id, semis[0].blue_cp_id
        finish_match(db, semis[0], first_red, "POINTS")
        finish_match(db, semis[1], semis[1].red_cp_id, "POINTS")
        final = db.scalar(select(Match).where(Match.category_id == cid, Match.stage == "knockout", Match.round_no == 2, Match.is_third_place.is_(False)))
        assert first_red in (final.red_cp_id, final.blue_cp_id)
        corrected = db.get(Match, semis[0].id)
        correct_finished_match(db, corrected, red_score=0, blue_score=2, red_warnings=0, blue_warnings=0, winner_cp_id=first_blue, reason="POINTS")
        final = db.get(Match, final.id)
        bronze = db.scalar(select(Match).where(Match.category_id == cid, Match.stage == "knockout", Match.is_third_place.is_(True)))
        assert first_blue in (final.red_cp_id, final.blue_cp_id)
        assert first_red in (bronze.red_cp_id, bronze.blue_cp_id)
        assert final.status == "ready" and bronze.status == "ready"


def test_knockout_winner_correction_is_blocked_after_dependent_fight_started():
    cid = create_category("knockout", 4)
    with SessionLocal() as db:
        c = db.get(Category, cid); generate_knockout(db, c)
        semis = db.scalars(select(Match).where(Match.category_id == cid, Match.stage == "knockout", Match.round_no == 1, Match.is_third_place.is_(False)).order_by(Match.match_no)).all()
        finish_match(db, semis[0], semis[0].red_cp_id, "POINTS")
        finish_match(db, semis[1], semis[1].red_cp_id, "POINTS")
        final = db.scalar(select(Match).where(Match.category_id == cid, Match.stage == "knockout", Match.round_no == 2, Match.is_third_place.is_(False)))
        final.status = "in_progress"; db.commit()
        m = db.get(Match, semis[0].id)
        try:
            correct_finished_match(db, m, red_score=0, blue_score=1, red_warnings=0, blue_warnings=0, winner_cp_id=m.blue_cp_id, reason="POINTS")
            assert False, "winner change must be blocked"
        except ValueError:
            pass


def test_swiss_correction_drops_unstarted_later_round():
    cid = create_category("swiss", 6, swiss_rounds=3)
    with SessionLocal() as db:
        c = db.get(Category, cid); r1 = generate_swiss_round(db, c); start_swiss_round(db, c)
        for m in r1:
            if m.status != "finished": finish_match(db, m, m.red_cp_id, "POINTS")
        generate_swiss_round(db, c)
        assert db.scalar(select(Match.id).where(Match.category_id == cid, Match.stage == "swiss", Match.round_no == 2))
        m = db.get(Match, r1[0].id)
        winner = m.blue_cp_id if m.blue_cp_id else m.red_cp_id
        correct_finished_match(db, m, red_score=0, blue_score=1 if m.blue_cp_id else 0, red_warnings=0, blue_warnings=0, winner_cp_id=winner, reason="POINTS")
        assert db.scalar(select(Match.id).where(Match.category_id == cid, Match.stage == "swiss", Match.round_no == 2)) is None



def test_group_generation_spreads_repeat_appearances_before_stage_start():
    cid = create_category("groups", 5, group_target_size=5)
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generated = generate_groups(db, c)
        group_a = sorted(
            [m for m in generated if m.group_name == "A"],
            key=lambda m: m.match_no,
        )
        assert len(group_a) == 10
        # Для пяти бойцов существует порядок без соседних повторных выходов;
        # генератор должен находить его ещё до назначения боёв на площадку.
        for previous, current in zip(group_a, group_a[1:]):
            assert not ({previous.red_cp_id, previous.blue_cp_id} & {current.red_cp_id, current.blue_cp_id})


def test_group_generation_uses_best_effort_for_four_fighters():
    cid = create_category("groups", 4, group_target_size=4)
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generated = generate_groups(db, c)
        group_a = sorted(
            [m for m in generated if m.group_name == "A"],
            key=lambda m: m.match_no,
        )
        overlaps = sum(
            1
            for previous, current in zip(group_a, group_a[1:])
            if {previous.red_cp_id, previous.blue_cp_id} & {current.red_cp_id, current.blue_cp_id}
        )
        # Для K4 есть только три непересекающиеся пары рёбер; два соседних повтора неизбежны.
        assert overlaps == 2

def test_single_area_generator_avoids_back_to_back_participant_when_possible():
    reset_db()
    with SessionLocal() as db:
        t = Tournament(name="Queue", avoid_consecutive_matches=True, preferred_match_gap=1)
        db.add(t); db.flush()
        area = Area(tournament_id=t.id, name="Площадка 1"); db.add(area)
        c = Category(tournament_id=t.id, name="Group", format="groups", group_target_size=4)
        db.add(c); db.flush()
        for i in range(4):
            p = Participant(tournament_id=t.id, last_name=f"Q{i+1}")
            db.add(p); db.flush(); add_category_participant(db, c.id, p.id)
        db.commit()
        generate_groups(db, c); start_group_stage(db, c)
        queued = db.scalars(select(Match).where(Match.area_id == area.id, Match.status.in_(["ready", "pending"])).order_by(Match.queue_order, Match.id)).all()
        assert len(queued) == 6
        from app.engine import queue_repeat_warnings
        # Полный круговой турнир четырёх участников не может обойтись без соседних пересечений;
        # в оптимальном порядке остаются два неизбежных перехода.
        assert len(queue_repeat_warnings(queued, 1)) <= 2


def test_explicit_queue_optimizer_respects_configured_gap_best_effort():
    reset_db()
    with SessionLocal() as db:
        from app.engine import optimize_area_queue, queue_repeat_warnings
        t = Tournament(name="Queue", avoid_consecutive_matches=True, preferred_match_gap=1)
        db.add(t); db.flush()
        area = Area(tournament_id=t.id, name="Площадка 1"); db.add(area)
        c = Category(tournament_id=t.id, name="Group", format="groups", group_target_size=4)
        db.add(c); db.flush()
        for i in range(4):
            p = Participant(tournament_id=t.id, last_name=f"R{i+1}")
            db.add(p); db.flush(); add_category_participant(db, c.id, p.id)
        db.commit(); generate_groups(db, c); start_group_stage(db, c)
        rows = db.scalars(select(Match).where(Match.area_id == area.id).order_by(Match.queue_order, Match.id)).all()
        # Сначала намеренно формируем плохой порядок. Генератор групп теперь
        # учитывает отдых, поэтому строим цепочку с максимально частым повтором бойца.
        remaining = list(rows)
        poor_order = [remaining.pop(0)]
        while remaining:
            previous_ids = {poor_order[-1].red_cp_id, poor_order[-1].blue_cp_id}
            next_idx = next(
                (i for i, m in enumerate(remaining) if previous_ids & {m.red_cp_id, m.blue_cp_id}),
                0,
            )
            poor_order.append(remaining.pop(next_idx))
        for idx, m in enumerate(poor_order, 1):
            m.queue_order = idx
        area.current_match_id = None
        db.flush()
        poor = db.scalars(select(Match).where(Match.area_id == area.id, Match.status.in_(["ready", "pending"])).order_by(Match.queue_order, Match.id)).all()
        before = len(queue_repeat_warnings(poor, 1))
        warnings = optimize_area_queue(db, area)
        ordered = db.scalars(select(Match).where(Match.area_id == area.id, Match.status.in_(["ready", "pending"])).order_by(Match.queue_order, Match.id)).all()
        after = len(queue_repeat_warnings(ordered, 1))
        assert warnings == after
        assert after < before
        assert after <= 2



def _finish_as_red(db, match, red_score=10, blue_score=5, reason="POINTS"):
    match.red_score = red_score
    match.blue_score = blue_score
    db.flush()
    finish_match(db, match, match.red_cp_id, reason)


def test_knockout_standings_rank_stage_before_score_and_score_inside_stage():
    cid = create_category("knockout", 16)
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generate_knockout(db, c)

        first = db.scalars(select(Match).where(
            Match.category_id == cid, Match.stage == "knockout", Match.round_no == 1,
            Match.is_third_place.is_(False),
        ).order_by(Match.match_no)).all()
        loser_scores = [9, 2, 7, 4, 8, 3, 6, 5]
        first_round_losers = {}
        for m, loser_score in zip(first, loser_scores):
            first_round_losers[m.blue_cp_id] = loser_score
            _finish_as_red(db, m, 10, loser_score)

        for rnd in (2, 3):
            rows = db.scalars(select(Match).where(
                Match.category_id == cid, Match.stage == "knockout", Match.round_no == rnd,
                Match.is_third_place.is_(False),
            ).order_by(Match.match_no)).all()
            for idx, m in enumerate(rows):
                _finish_as_red(db, m, 10, 6 - idx)

        bronze = db.scalar(select(Match).where(Match.category_id == cid, Match.is_third_place.is_(True)))
        final = db.scalar(select(Match).where(
            Match.category_id == cid, Match.stage == "knockout", Match.round_no == 4,
            Match.is_third_place.is_(False),
        ))
        _finish_as_red(db, bronze, 10, 7)
        live_rows = standings(db, cid)
        assert {live_rows[0]["cp_id"], live_rows[1]["cp_id"]} == {final.red_cp_id, final.blue_cp_id}
        assert [live_rows[2]["stage_label"], live_rows[3]["stage_label"]] == ["3-е место", "Бой за 3-е место"]

        _finish_as_red(db, final, 10, 8)

        rows = standings(db, cid)
        assert len(rows) == 16
        assert [r["place"] for r in rows] == list(range(1, 17))
        assert rows[0]["stage_label"] == "Победитель"
        assert rows[1]["stage_label"] == "Финал"
        assert rows[2]["stage_label"] == "3-е место"
        assert rows[3]["stage_label"] == "Бой за 3-е место"
        assert all(r["stage_label"] == "1/4 финала" for r in rows[4:8])
        assert all(r["stage_label"] == "1/8 финала" for r in rows[8:])

        # Все проигравшие в 1/8 дошли до одной стадии, поэтому внутри неё
        # ничью по стадии разрешает счёт выбывания: 9:10 выше 8:10, ..., 2:10.
        ordered_scores = [first_round_losers[r["cp_id"]] for r in rows[8:]]
        assert ordered_scores == sorted(loser_scores, reverse=True)


def test_group_playoff_standings_put_playoff_progress_above_group_only_fighters():
    cid = create_category("groups", 8, group_target_size=4, group_qualifiers=2)
    with SessionLocal() as db:
        c = db.get(Category, cid)
        generate_groups(db, c)
        start_group_stage(db, c)
        for m in db.scalars(select(Match).where(Match.category_id == cid, Match.stage == "group").order_by(Match.match_no)).all():
            _finish_as_red(db, m, 5, 3)

        generate_group_playoff(db, c)
        semis = db.scalars(select(Match).where(
            Match.category_id == cid, Match.stage == "playoff", Match.round_no == 1,
            Match.is_third_place.is_(False),
        ).order_by(Match.match_no)).all()
        for idx, m in enumerate(semis):
            _finish_as_red(db, m, 10, 8 - idx)
        bronze = db.scalar(select(Match).where(Match.category_id == cid, Match.stage == "playoff", Match.is_third_place.is_(True)))
        final = db.scalar(select(Match).where(
            Match.category_id == cid, Match.stage == "playoff", Match.round_no == 2,
            Match.is_third_place.is_(False),
        ))
        _finish_as_red(db, bronze, 10, 7)
        _finish_as_red(db, final, 10, 9)

        rows = standings(db, cid)
        assert len(rows) == 8
        assert [r["stage_label"] for r in rows[:4]] == ["Победитель", "Финал", "3-е место", "Бой за 3-е место"]
        assert all(r["stage_label"] == "Групповой этап" for r in rows[4:])
        assert all(r["ranking_type"] == "elimination" for r in rows)


def test_knockout_draw_is_rejected_even_if_winner_is_supplied():
    cid = create_category("knockout", 2)
    with SessionLocal() as db:
        category = db.get(Category, cid)
        generate_knockout(db, category)
        match = db.scalar(select(Match).where(Match.category_id == cid, Match.status == "ready"))
        try:
            finish_match(db, match, match.red_cp_id, "DRAW")
        except ValueError as exc:
            assert "Ничья" in str(exc)
        else:
            raise AssertionError("Олимпийский бой ошибочно принят как ничья")


def test_finish_rejects_empty_winner_and_unknown_reason():
    cid = create_category("knockout", 2)
    with SessionLocal() as db:
        category = db.get(Category, cid)
        generate_knockout(db, category)
        match = db.scalar(select(Match).where(Match.category_id == cid, Match.status == "ready"))
        for winner, reason in ((None, "POINTS"), (match.red_cp_id, "UNKNOWN")):
            try:
                finish_match(db, match, winner, reason)
            except ValueError:
                pass
            else:
                raise AssertionError("Некорректный результат был принят")


def test_score_delta_must_be_configured_in_category_rules():
    cid = create_category("knockout", 2)
    with SessionLocal() as db:
        category = db.get(Category, cid)
        generate_knockout(db, category)
        match = db.scalar(select(Match).where(Match.category_id == cid, Match.status == "ready"))
        from app.engine import apply_score
        try:
            apply_score(db, match, "red", 99)
        except ValueError as exc:
            assert "правилами категории" in str(exc)
        else:
            raise AssertionError("Произвольное изменение счёта было принято")
