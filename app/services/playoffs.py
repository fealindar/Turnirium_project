"""Плей-офф после групп и ручная перестройка олимпийских слотов."""

from __future__ import annotations

import math
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import Area, Category, CategoryParticipant, Match, MatchEvent
from .brackets import _create_third_place_match, _maybe_activate_or_bye, generate_knockout
from .common import audit
from .group_playoff_seeding import seed_group_playoff_slots
from .scheduling import auto_assign_ready_matches
from .standings import standings

def generate_group_playoff(db: Session, category: Category) -> list[Match]:
    unfinished = db.scalar(select(func.count(Match.id)).where(Match.category_id == category.id, Match.stage == "group", Match.status != "finished"))
    if unfinished:
        raise ValueError("Сначала завершите все групповые поединки")
    existing = db.scalar(select(func.count(Match.id)).where(Match.category_id == category.id, Match.stage == "playoff"))
    if existing:
        raise ValueError("Плей-офф уже создан")
    group_names = [x for x in db.scalars(select(CategoryParticipant.group_name).where(CategoryParticipant.category_id == category.id).distinct()).all() if x]
    group_rows = {g: standings(db, category.id, g) for g in sorted(group_names)}
    # Используем уже рассчитанные места в группах. Клубы и города влияли
    # на создание групп, но не должны менять спортивный посев плей-офф.
    top_by_group: dict[str, list[int | None]] = {}
    for group, rows in group_rows.items():
        # При исключении участника сохраняем его исходное место в таблице:
        # второй номер группы не должен автоматически становиться первым сеяным.
        ranked_ids: list[int | None] = []
        selected = 0
        for row in rows:
            eligible = not row["disqualified"] and row.get("participant_status") != "withdrawn"
            ranked_ids.append(row["cp_id"] if eligible else None)
            if eligible:
                selected += 1
            if selected == category.group_qualifiers:
                break
        top_by_group[group] = ranked_ids
    qualifiers_count = sum(cid is not None for ids in top_by_group.values() for cid in ids)
    if qualifiers_count < 2:
        raise ValueError("Недостаточно участников для плей-офф")
    slot_values = seed_group_playoff_slots(top_by_group)

    # Сохраняем групповые бои и добавляем отдельную сетку плей-офф.
    slots = len(slot_values)
    rounds = int(math.log2(slots))
    by_round: dict[int, list[Match]] = {}
    match_no = (db.scalar(select(func.max(Match.match_no)).where(Match.category_id == category.id)) or 0) + 1
    for rnd in range(1, rounds + 1):
        count = slots // (2 ** rnd)
        by_round[rnd] = []
        for _ in range(count):
            m = Match(category_id=category.id, stage="playoff", round_no=rnd, match_no=match_no,
                      status="blocked" if rnd > 1 else "pending",
                      duration_ms=category.match_duration_sec * 1000, remaining_ms=category.match_duration_sec * 1000)
            match_no += 1
            db.add(m)
            by_round[rnd].append(m)
        db.flush()
    for rnd in range(1, rounds):
        for idx, m in enumerate(by_round[rnd]):
            target = by_round[rnd + 1][idx // 2]
            m.next_match_id = target.id
            m.next_slot = "red" if idx % 2 == 0 else "blue"
            if idx % 2 == 0:
                target.source_red_match_id = m.id
            else:
                target.source_blue_match_id = m.id
    if rounds >= 2:
        _create_third_place_match(db, category, "playoff", by_round[rounds - 1], match_no, rounds)
        match_no += 1
    for idx, m in enumerate(by_round[1]):
        m.red_cp_id = slot_values[idx * 2]
        m.blue_cp_id = slot_values[idx * 2 + 1]
    db.flush()
    for m in by_round[1]:
        _maybe_activate_or_bye(db, m)
    auto_assign_ready_matches(db, category.tournament_id)
    audit(db, category.tournament_id, "PLAYOFF_GENERATED", "category", category.id, payload={"qualifiers": qualifiers_count, "seeding": "group_rank"})
    db.commit()
    return [m for rnd in by_round.values() for m in rnd]

def rebuild_bracket_stage_from_slots(db: Session, category: Category, stage: str, slot_cp_ids: list[int | None]) -> list[Match]:
    """Перестраивает незапущенную олимпийскую сетку по видимым слотам первого раунда."""
    if stage not in {"knockout", "playoff"}:
        raise ValueError("Перетаскивание по ветвям доступно только для олимпийской сетки и плей-офф")
    real_started = db.scalar(select(func.count(Match.id)).where(
        Match.category_id == category.id,
        Match.stage == stage,
        ((Match.status == "in_progress") | ((Match.status == "finished") & (Match.result_reason != "BYE"))),
    ))
    if real_started:
        raise ValueError("Ветви нельзя менять после начала поединков этого этапа")

    if stage == "knockout":
        return generate_knockout(db, category, stage="knockout", slot_cp_ids=slot_cp_ids)

    current_first = db.scalars(select(Match).where(
        Match.category_id == category.id, Match.stage == "playoff", Match.round_no == 1
    ).order_by(Match.match_no)).all()
    if not current_first:
        raise ValueError("Плей-офф еще не создан")
    allowed = {cid for m in current_first for cid in (m.red_cp_id, m.blue_cp_id) if cid}
    supplied = [cid for cid in slot_cp_ids if cid]
    if len(supplied) != len(set(supplied)) or set(supplied) != allowed:
        raise ValueError("Можно только переставлять уже вышедших в плей-офф участников")
    slots = len(current_first) * 2
    if len(slot_cp_ids) > slots:
        raise ValueError("Число слотов превышает размер сетки")
    normalized = list(slot_cp_ids) + [None] * (slots - len(slot_cp_ids))

    old_ids = select(Match.id).where(Match.category_id == category.id, Match.stage == "playoff")
    for area in db.scalars(select(Area).where(Area.current_match_id.in_(old_ids))).all():
        area.current_match_id = None
    db.execute(delete(MatchEvent).where(MatchEvent.match_id.in_(old_ids)))
    db.execute(delete(Match).where(Match.category_id == category.id, Match.stage == "playoff"))
    db.flush()

    rounds = int(math.log2(slots))
    by_round: dict[int, list[Match]] = {}
    match_no = (db.scalar(select(func.max(Match.match_no)).where(Match.category_id == category.id)) or 0) + 1
    for rnd in range(1, rounds + 1):
        count = slots // (2 ** rnd)
        by_round[rnd] = []
        for _ in range(count):
            m = Match(
                category_id=category.id, stage="playoff", round_no=rnd, match_no=match_no,
                status="blocked" if rnd > 1 else "pending",
                duration_ms=category.match_duration_sec * 1000,
                remaining_ms=category.match_duration_sec * 1000,
            )
            match_no += 1
            db.add(m)
            by_round[rnd].append(m)
        db.flush()
    for rnd in range(1, rounds):
        for idx, m in enumerate(by_round[rnd]):
            target = by_round[rnd + 1][idx // 2]
            m.next_match_id = target.id
            m.next_slot = "red" if idx % 2 == 0 else "blue"
            if idx % 2 == 0:
                target.source_red_match_id = m.id
            else:
                target.source_blue_match_id = m.id
    if rounds >= 2:
        _create_third_place_match(db, category, "playoff", by_round[rounds - 1], match_no, rounds)
        match_no += 1
    for idx, m in enumerate(by_round[1]):
        m.red_cp_id = normalized[idx * 2]
        m.blue_cp_id = normalized[idx * 2 + 1]
    db.flush()
    for m in by_round[1]:
        _maybe_activate_or_bye(db, m)
    auto_assign_ready_matches(db, category.tournament_id)
    audit(db, category.tournament_id, "PLAYOFF_REARRANGED", "category", category.id)
    db.commit()
    return [m for rows in by_round.values() for m in rows]
