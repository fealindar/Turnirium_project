"""Построение и обслуживание олимпийской сетки."""

from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, CategoryParticipant, Match
from .common import _affiliation_penalty, _norm, audit, clear_category_matches, now_utc
from .scheduling import auto_assign_ready_matches

def _spread_knockout_slots(cps: list[CategoryParticipant], slots: int) -> list[int | None]:
    """Жадно разводит участников: сначала по клубам, затем по городам.

    Результат — конкретный список слотов, включая BYE. Алгоритм детерминирован,
    чтобы повторная генерация категории не меняла жеребьёвку неожиданно.
    """
    if not cps:
        return [None] * slots
    # Раскладка BYE как в _first_round_slots: сначала даём каждому бою первого
    # раунда по участнику, затем заполняем противоположные стороны.
    match_count = slots // 2
    entrant_positions = [2 * i for i in range(match_count)]
    entrant_positions += [2 * i + 1 for i in range(match_count - 1, -1, -1)]
    entrant_positions = entrant_positions[:len(cps)]

    club_freq: dict[str, int] = defaultdict(int)
    city_freq: dict[str, int] = defaultdict(int)
    for cp in cps:
        club_freq[_norm(cp.participant.club)] += 1
        city_freq[_norm(cp.participant.city)] += 1
    ordered = sorted(
        cps,
        key=lambda cp: (
            -club_freq.get(_norm(cp.participant.club), 0),
            -city_freq.get(_norm(cp.participant.city), 0),
            cp.seed_order,
            cp.id,
        ),
    )
    result: list[int | None] = [None] * slots
    placed: list[tuple[int, CategoryParticipant]] = []
    available = entrant_positions[:]
    for cp in ordered:
        best_pos = available[0]
        best_score = None
        for pos in available:
            score = 0
            for other_pos, other in placed:
                affinity = _affiliation_penalty(cp, other)
                if not affinity:
                    continue
                # Сильнее штрафуем попадание в одну и ту же всё более узкую ветку сетки.
                block = slots
                proximity = 1
                while block >= 2:
                    if pos // block == other_pos // block:
                        score += affinity * proximity
                    block //= 2
                    proximity *= 3
            # Стабильный тай-брейк удерживает посев близко к естественной позиции.
            score += abs(entrant_positions[min(len(placed), len(entrant_positions) - 1)] - pos)
            if best_score is None or score < best_score or (score == best_score and pos < best_pos):
                best_score, best_pos = score, pos
        result[best_pos] = cp.id
        available.remove(best_pos)
        placed.append((best_pos, cp))
    return result

def _first_round_slots(cp_ids: list[int], match_count: int) -> list[int | None]:
    """Распределяет BYE так, чтобы при двух и более участниках не было пустого боя первого раунда."""
    pairs: list[list[int | None]] = [[None, None] for _ in range(match_count)]
    idx = 0
    # Сначала даём каждому бою по одному участнику.
    for i in range(match_count):
        if idx < len(cp_ids):
            pairs[i][0] = cp_ids[idx]
            idx += 1
    # Вторые стороны заполняем с конца, равномернее распределяя BYE.
    for i in range(match_count - 1, -1, -1):
        if idx < len(cp_ids):
            pairs[i][1] = cp_ids[idx]
            idx += 1
    return [v for pair in pairs for v in pair]

def next_power_of_two(n: int) -> int:
    return 1 if n <= 1 else 2 ** math.ceil(math.log2(n))

def _maybe_activate_or_bye(db: Session, match: Match) -> None:
    if match.status == "finished":
        return
    if match.red_cp_id and match.blue_cp_id:
        match.status = "ready"
        return

    # Пустой слот первого раунда — настоящий BYE; следующие раунды ждут оба исходных боя.
    sources = [sid for sid in (match.source_red_match_id, match.source_blue_match_id) if sid]
    all_sources_done = True
    if sources:
        all_sources_done = all((db.get(Match, sid) and db.get(Match, sid).status == "finished") for sid in sources)
    if (not sources or all_sources_done) and bool(match.red_cp_id) ^ bool(match.blue_cp_id):
        winner_id = match.red_cp_id or match.blue_cp_id
        match.winner_cp_id = winner_id
        match.status = "finished"
        match.result_reason = "BYE"
        match.remaining_ms = match.duration_ms
        match.finished_at = now_utc()
        db.flush()
        propagate_winner(db, match)
        _propagate_loser_to_third_place(db, match)
    elif not match.red_cp_id and not match.blue_cp_id:
        match.status = "blocked"
    else:
        match.status = "blocked"

def propagate_winner(db: Session, match: Match) -> None:
    if not match.next_match_id or not match.winner_cp_id:
        return
    nxt = db.get(Match, match.next_match_id)
    if not nxt:
        return
    if match.next_slot == "red":
        nxt.red_cp_id = match.winner_cp_id
    else:
        nxt.blue_cp_id = match.winner_cp_id
    db.flush()
    _maybe_activate_or_bye(db, nxt)

def _third_place_match(db: Session, category_id: int, stage: str) -> Match | None:
    return db.scalar(select(Match).where(
        Match.category_id == category_id, Match.stage == stage, Match.is_third_place.is_(True)
    ))

def _create_third_place_match(db: Session, category: Category, stage: str, semifinals: list[Match], match_no: int, round_no: int) -> Match | None:
    if len(semifinals) != 2:
        return None

    # Бой за третье место должен идти непосредственно перед финалом. Сетка строится
    # заранее, поэтому передаём последний обычный номер бронзовому бою, а финал сдвигаем.
    bronze_match_no = match_no
    final_id = semifinals[0].next_match_id
    if final_id and final_id == semifinals[1].next_match_id:
        final = db.get(Match, final_id)
        if final and not final.is_third_place:
            bronze_match_no = final.match_no
            final.match_no += 1

    bronze = Match(
        category_id=category.id, stage=stage, round_no=round_no, match_no=bronze_match_no,
        is_third_place=True, status="blocked",
        source_red_match_id=semifinals[0].id, source_blue_match_id=semifinals[1].id,
        duration_ms=category.match_duration_sec * 1000,
        remaining_ms=category.match_duration_sec * 1000,
    )
    db.add(bronze)
    db.flush()
    return bronze

def _propagate_loser_to_third_place(db: Session, match: Match) -> None:
    if match.is_third_place:
        return
    bronze = _third_place_match(db, match.category_id, match.stage)
    if not bronze or match.id not in (bronze.source_red_match_id, bronze.source_blue_match_id):
        return
    loser_id = None
    if match.red_cp_id and match.blue_cp_id and match.winner_cp_id:
        loser_id = match.blue_cp_id if match.winner_cp_id == match.red_cp_id else match.red_cp_id
    if match.id == bronze.source_red_match_id:
        bronze.red_cp_id = loser_id
    else:
        bronze.blue_cp_id = loser_id
    sources = [db.get(Match, bronze.source_red_match_id), db.get(Match, bronze.source_blue_match_id)]
    if all(src and src.status == "finished" for src in sources):
        if bronze.red_cp_id and bronze.blue_cp_id:
            bronze.status = "ready"
        elif bronze.red_cp_id or bronze.blue_cp_id:
            bronze.winner_cp_id = bronze.red_cp_id or bronze.blue_cp_id
            bronze.status = "finished"
            bronze.result_reason = "BYE"
            bronze.finished_at = now_utc()
        else:
            bronze.status = "blocked"
    db.flush()

def generate_knockout(
    db: Session,
    category: Category,
    ordered_cp_ids: list[int] | None = None,
    stage: str = "knockout",
    slot_cp_ids: list[int | None] | None = None,
) -> list[Match]:
    clear_category_matches(db, category)
    cps = db.scalars(select(CategoryParticipant).where(
        CategoryParticipant.category_id == category.id,
        CategoryParticipant.disqualified.is_(False),
    ).order_by(CategoryParticipant.seed_order, CategoryParticipant.id)).all()
    cps = [cp for cp in cps if cp.participant.active and cp.participant.status != "withdrawn"]
    if ordered_cp_ids:
        by_id = {cp.id: cp for cp in cps}
        ordered = [by_id[cid] for cid in ordered_cp_ids if cid in by_id]
        ordered += [cp for cp in cps if cp.id not in set(ordered_cp_ids)]
        cps = ordered
        for idx, cp in enumerate(cps, 1):
            cp.seed_order = idx
    if len(cps) < 2:
        raise ValueError("Для сетки нужно минимум 2 участника")

    slots = next_power_of_two(len(cps))
    rounds = int(math.log2(slots))
    by_round: dict[int, list[Match]] = {}
    match_no = 1
    for rnd in range(1, rounds + 1):
        count = slots // (2 ** rnd)
        by_round[rnd] = []
        for _ in range(count):
            m = Match(
                category_id=category.id,
                stage=stage,
                round_no=rnd,
                match_no=match_no,
                status="blocked" if rnd > 1 else "pending",
                duration_ms=category.match_duration_sec * 1000,
                remaining_ms=category.match_duration_sec * 1000,
            )
            match_no += 1
            db.add(m)
            by_round[rnd].append(m)
        db.flush()

    for rnd in range(1, rounds):
        current = by_round[rnd]
        nxt = by_round[rnd + 1]
        for idx, m in enumerate(current):
            target = nxt[idx // 2]
            m.next_match_id = target.id
            m.next_slot = "red" if idx % 2 == 0 else "blue"
            if idx % 2 == 0:
                target.source_red_match_id = m.id
            else:
                target.source_blue_match_id = m.id

    if rounds >= 2:
        _create_third_place_match(db, category, stage, by_round[rounds - 1], match_no, rounds)
        match_no += 1

    first = by_round[1]
    # Заполняем последовательно; пустые слоты становятся BYE и автоматически продвигаются.
    cp_iter = iter(cps)
    if slot_cp_ids is not None:
        slot_values = list(slot_cp_ids[:slots]) + [None] * max(0, slots - len(slot_cp_ids))
        valid = {cp.id for cp in cps}
        seen: set[int] = set()
        cleaned: list[int | None] = []
        for cid in slot_values:
            if cid in valid and cid not in seen:
                cleaned.append(cid)
                seen.add(cid)
            else:
                cleaned.append(None)
        slot_values = cleaned
        missing = [cp.id for cp in cps if cp.id not in {cid for cid in slot_values if cid}]
        for idx, value in enumerate(slot_values):
            if value is None and missing:
                slot_values[idx] = missing.pop(0)
    elif ordered_cp_ids:
        slot_values = _first_round_slots([cp.id for cp in cps], len(first))
    else:
        slot_values = _spread_knockout_slots(cps, slots)
    for idx, m in enumerate(first):
        m.red_cp_id = slot_values[idx * 2]
        m.blue_cp_id = slot_values[idx * 2 + 1]
    db.flush()
    for m in list(first):
        _maybe_activate_or_bye(db, m)
    category.status = "ready"
    category.bracket_locked = False
    auto_assign_ready_matches(db, category.tournament_id)
    audit(db, category.tournament_id, "BRACKET_GENERATED", "category", category.id, payload={"format": stage, "participants": len(cps)})
    db.commit()
    return db.scalars(select(Match).where(Match.category_id == category.id).order_by(Match.round_no, Match.match_no)).all()
