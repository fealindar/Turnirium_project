"""Регрессии спортивного посева плей-офф, не затрагивающие жеребьёвку групп."""

from __future__ import annotations

from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.engine import finish_match, generate_group_playoff, rebuild_bracket_stage_from_slots
from app.models import (
    Area, AuditEvent, Category, CategoryParticipant, CategoryTemplate,
    Match, MatchEvent, Participant, Tournament,
)
from app.services.group_playoff_seeding import seed_group_playoff_slots


def _ranking(groups: int, qualifiers: int) -> dict[str, list[int]]:
    return {
        chr(ord("A") + group): [100 * (group + 1) + place for place in range(1, qualifiers + 1)]
        for group in range(groups)
    }


def _seed_positions(layout: list[int | None]) -> dict[int, int]:
    return {cp_id: pos for pos, cp_id in enumerate(layout) if cp_id is not None}


def _no_first_round_rematches(layout: list[int | None], ranks: dict[str, list[int]]) -> None:
    group_of = {cp_id: group for group, ids in ranks.items() for cp_id in ids}
    for red, blue in zip(layout[::2], layout[1::2]):
        if red is not None and blue is not None:
            assert group_of[red] != group_of[blue]


def test_two_groups_first_places_vs_other_groups_last_places():
    ranks = _ranking(2, 2)
    layout = seed_group_playoff_slots(ranks)
    pairs = {frozenset(pair) for pair in zip(layout[::2], layout[1::2])}
    assert pairs == {
        frozenset((ranks["A"][0], ranks["B"][1])),
        frozenset((ranks["B"][0], ranks["A"][1])),
    }
    assert seed_group_playoff_slots(ranks) == layout


def test_four_groups_winners_in_distinct_quarters_and_against_lower_places():
    ranks = _ranking(4, 2)
    layout = seed_group_playoff_slots(ranks)
    positions = _seed_positions(layout)
    assert {positions[ids[0]] // 2 for ids in ranks.values()} == {0, 1, 2, 3}
    _no_first_round_rematches(layout, ranks)
    for red, blue in zip(layout[::2], layout[1::2]):
        assert red is not None and blue is not None
        places = {1 if red == ids[0] else 2 for ids in ranks.values() if red in ids}
        places |= {1 if blue == ids[0] else 2 for ids in ranks.values() if blue in ids}
        assert places == {1, 2}


def test_three_groups_two_qualifiers_no_same_group_rematches_and_byes_for_winners():
    ranks = _ranking(3, 2)
    layout = seed_group_playoff_slots(ranks)
    _no_first_round_rematches(layout, ranks)
    winners = {ids[0] for ids in ranks.values()}
    byes = {red or blue for red, blue in zip(layout[::2], layout[1::2]) if not red or not blue}
    assert len(byes) == 2
    assert byes <= winners
    assert len({red for red in layout if red is not None}) == 6


def test_two_groups_three_qualifiers_byes_for_winners_and_cross_group_matches():
    ranks = _ranking(2, 3)
    layout = seed_group_playoff_slots(ranks)
    assert len(layout) == 8
    _no_first_round_rematches(layout, ranks)
    byes = {red or blue for red, blue in zip(layout[::2], layout[1::2]) if red is None or blue is None}
    assert byes == {ranks["A"][0], ranks["B"][0]}


def test_all_qualify_still_produces_cross_group_first_round_and_separated_winners():
    ranks = _ranking(2, 4)
    layout = seed_group_playoff_slots(ranks)
    _no_first_round_rematches(layout, ranks)
    positions = _seed_positions(layout)
    assert positions[ranks["A"][0]] // 4 != positions[ranks["B"][0]] // 4
    assert len(set(layout)) == 8


def test_uneven_groups_with_exclusion_keep_actual_places():
    ranks = {"A": [101, 102, 103, 104], "B": [None, 202, 203, 204]}
    layout = seed_group_playoff_slots(ranks)
    assert set(layout) - {None} == {101, 102, 103, 104, 202, 203, 204}
    # Единственный BYE должен достаться реальному победителю A, а не B2.
    byes = {red or blue for red, blue in zip(layout[::2], layout[1::2]) if red is None or blue is None}
    assert 101 in byes
    assert 202 not in byes
    assert seed_group_playoff_slots(ranks) == layout


def test_seeded_bracket_is_stable_for_multiple_group_counts():
    for groups, qualifying in ((2, 2), (2, 3), (2, 4), (3, 2), (4, 2), (4, 3), (4, 4), (6, 2), (8, 3)):
        ranks = _ranking(groups, qualifying)
        layout = seed_group_playoff_slots(ranks)
        _no_first_round_rematches(layout, ranks)
        assert len(layout) & (len(layout) - 1) == 0
        assert {cp for cp in layout if cp is not None} == {cp for ids in ranks.values() for cp in ids}


def test_group_playoff_integration_and_manual_rebuild_before_first_fight():
    init_db()
    with SessionLocal() as db:
        for model in (MatchEvent, AuditEvent, Match, Area, CategoryParticipant, Participant, Category, Tournament, CategoryTemplate):
            db.execute(delete(model))
        t = Tournament(name="Посев плей-офф")
        db.add(t)
        db.flush()
        arena = Area(tournament_id=t.id, name="Площадка 1")
        db.add(arena)
        cat = Category(tournament_id=t.id, name="Группы", format="groups", group_qualifiers=2)
        db.add(cat)
        db.flush()
        qualifiers = _ranking(2, 2)
        for group, ids in qualifiers.items():
            for place, cid in enumerate(ids):
                # Все бойцы из одного клуба: спортивный посев не должен
                # повторно разводить их по клубам поверх уже готовых групп.
                person = Participant(tournament_id=t.id, last_name=f"{group}{place + 1}", club="Один клуб")
                db.add(person)
                db.flush()
                link = CategoryParticipant(category_id=cat.id, participant_id=person.id, group_name=group)
                db.add(link)
                db.flush()
                ids[place] = link.id
            db.add(Match(
                category_id=cat.id, stage="group", group_name=group,
                match_no=len(group), round_no=1, status="finished",
                red_cp_id=ids[0], blue_cp_id=ids[1], winner_cp_id=ids[0],
                red_score=5, blue_score=0, result_reason="POINTS",
            ))
        db.commit()

        generate_group_playoff(db, cat)
        first = db.scalars(select(Match).where(
            Match.category_id == cat.id, Match.stage == "playoff", Match.round_no == 1,
        ).order_by(Match.match_no)).all()
        expected = {
            frozenset((qualifiers["A"][0], qualifiers["B"][1])),
            frozenset((qualifiers["B"][0], qualifiers["A"][1])),
        }
        assert {frozenset((m.red_cp_id, m.blue_cp_id)) for m in first} == expected
        assert all(m.area_id is None for m in first)

        # Сетка до первого реального боя должна редактироваться, в том числе
        # с очисткой события/привязки текущего поединка, без NameError.
        old_first_id = first[0].id
        arena.current_match_id = old_first_id
        event = MatchEvent(match_id=old_first_id, event_type="TEST")
        db.add(event)
        db.commit()
        old_event_id = event.id
        slots = [v for m in first for v in (m.red_cp_id, m.blue_cp_id)]
        slots[0], slots[2] = slots[2], slots[0]
        rebuild_bracket_stage_from_slots(db, cat, "playoff", slots)
        db.expire_all()
        new_first = db.scalars(select(Match).where(
            Match.category_id == cat.id, Match.stage == "playoff", Match.round_no == 1,
        ).order_by(Match.match_no)).all()
        assert [v for m in new_first for v in (m.red_cp_id, m.blue_cp_id)] == slots
        assert db.get(Area, arena.id).current_match_id is None
        assert db.get(MatchEvent, old_event_id) is None

        finish_match(db, new_first[0], new_first[0].red_cp_id, "POINTS")
        try:
            rebuild_bracket_stage_from_slots(db, cat, "playoff", slots)
        except ValueError as exc:
            assert "после начала" in str(exc)
        else:
            raise AssertionError("Нельзя менять сетку после первого завершённого боя")


def test_one_group_is_still_seeded_by_place():
    layout = seed_group_playoff_slots({"A": [11, 12, 13, 14]})
    assert {frozenset(pair) for pair in zip(layout[::2], layout[1::2])} == {
        frozenset((11, 14)), frozenset((12, 13)),
    }


def test_rebuild_playoff_with_byes_preserves_automatic_advancement():
    init_db()
    with SessionLocal() as db:
        for model in (MatchEvent, AuditEvent, Match, Area, CategoryParticipant, Participant, Category, Tournament, CategoryTemplate):
            db.execute(delete(model))
        tournament = Tournament(name="6 участников")
        db.add(tournament)
        db.flush()
        category = Category(
            tournament_id=tournament.id, name="Группы по три",
            format="groups", group_qualifiers=3,
        )
        db.add(category)
        db.flush()
        for group in ("A", "B"):
            cp_ids = []
            for place in range(1, 4):
                person = Participant(tournament_id=tournament.id, last_name=f"{group}{place}")
                db.add(person)
                db.flush()
                link = CategoryParticipant(
                    category_id=category.id, participant_id=person.id, group_name=group,
                )
                db.add(link)
                db.flush()
                cp_ids.append(link.id)
            for winner, loser in ((0, 1), (0, 2), (1, 2)):
                db.add(Match(
                    category_id=category.id, stage="group", group_name=group,
                    status="finished", result_reason="POINTS", winner_cp_id=cp_ids[winner],
                    red_cp_id=cp_ids[winner], blue_cp_id=cp_ids[loser],
                    red_score=5, blue_score=0,
                ))
        db.commit()

        generate_group_playoff(db, category)
        initial = db.scalars(select(Match).where(
            Match.category_id == category.id, Match.stage == "playoff", Match.round_no == 1,
        ).order_by(Match.match_no)).all()
        assert sum(m.result_reason == "BYE" for m in initial) == 2
        assert sum(m.status == "ready" for m in initial) == 2
        slots = [v for m in initial for v in (m.red_cp_id, m.blue_cp_id)]
        rebuild_bracket_stage_from_slots(db, category, "playoff", slots)
        db.expire_all()
        new_first = db.scalars(select(Match).where(
            Match.category_id == category.id, Match.stage == "playoff", Match.round_no == 1,
        ).order_by(Match.match_no)).all()
        assert [v for m in new_first for v in (m.red_cp_id, m.blue_cp_id)] == slots
        assert sum(m.result_reason == "BYE" for m in new_first) == 2
        second = db.scalars(select(Match).where(
            Match.category_id == category.id, Match.stage == "playoff", Match.round_no == 2,
        )).all()
        assert sum(bool(m.red_cp_id) + bool(m.blue_cp_id) for m in second) == 2
