"""Формирование и перестройка туров швейцарской системы."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Category, CategoryParticipant, Match
from .common import _affiliation_penalty, _layout_match_locked, audit, clear_category_matches, now_utc
from .scheduling import auto_assign_ready_matches
from .standings import standings

def swiss_current_round(db: Session, category_id: int) -> int:
    return db.scalar(select(func.max(Match.round_no)).where(Match.category_id == category_id, Match.stage == "swiss")) or 0

def _played_pairs(db: Session, category_id: int) -> set[frozenset[int]]:
    pairs = set()
    for m in db.scalars(select(Match).where(Match.category_id == category_id, Match.stage == "swiss")).all():
        if m.red_cp_id and m.blue_cp_id:
            pairs.add(frozenset((m.red_cp_id, m.blue_cp_id)))
    return pairs

def generate_swiss_round(db: Session, category: Category) -> list[Match]:
    current = swiss_current_round(db, category.id)
    if current:
        unfinished = db.scalar(select(func.count(Match.id)).where(Match.category_id == category.id, Match.stage == "swiss", Match.round_no == current, Match.status != "finished"))
        if unfinished:
            raise ValueError("Сначала завершите текущий швейцарский тур")
    if current >= category.swiss_rounds:
        raise ValueError("Настроенное количество швейцарских туров уже проведено")
    if current == 0:
        # В этой реализации швейцарский этап не смешивается с другими этапами.
        clear_category_matches(db, category)

    rows = standings(db, category.id, swiss_only=True)
    cps_by_id = {cp.id: cp for cp in db.scalars(select(CategoryParticipant).where(CategoryParticipant.category_id == category.id, CategoryParticipant.disqualified.is_(False))).all() if cp.participant.active and cp.participant.status != "withdrawn"}
    ordered_ids = [r["cp_id"] for r in rows if r["cp_id"] in cps_by_id]
    if current == 0:
        ordered_ids = [cp.id for cp in sorted(cps_by_id.values(), key=lambda c: (c.seed_order, c.id))]
    played = _played_pairs(db, category.id)
    pool = ordered_ids[:]
    pairs: list[tuple[int, int | None]] = []
    while pool:
        a = pool.pop(0)
        if not pool:
            pairs.append((a, None))
            break
        a_cp = cps_by_id[a]
        # Сначала избегаем повторных пар, затем совпадений клуба и города.
        # Разница рейтинга используется последней, сохраняя характер Swiss.
        scored = []
        for i, b in enumerate(pool):
            b_cp = cps_by_id[b]
            repeat = 1 if frozenset((a, b)) in played else 0
            affiliation = _affiliation_penalty(a_cp, b_cp)
            scored.append((repeat * 1_000_000 + affiliation, i))
        _, pick = min(scored)
        b = pool.pop(pick)
        pairs.append((a, b))

    next_round = current + 1
    match_no = (db.scalar(select(func.max(Match.match_no)).where(Match.category_id == category.id)) or 0) + 1
    created = []
    for a, b in pairs:
        m = Match(category_id=category.id, stage="swiss", round_no=next_round, match_no=match_no,
                  red_cp_id=a, blue_cp_id=b, status="staged",
                  winner_cp_id=None, result_reason="",
                  duration_ms=category.match_duration_sec * 1000, remaining_ms=category.match_duration_sec * 1000)
        db.add(m)
        created.append(m)
        match_no += 1
    db.flush()
    category.status = "ready"
    category.bracket_locked = False
    audit(db, category.tournament_id, "SWISS_ROUND_GENERATED", "category", category.id, payload={"round": next_round})
    db.commit()
    return created

def rebuild_swiss_round_from_slots(db: Session, category: Category, cp_ids: list[int | None]) -> list[Match]:
    current = swiss_current_round(db, category.id)
    if not current:
        raise ValueError("Swiss-тур еще не сформирован")
    rows = db.scalars(select(Match).where(
        Match.category_id == category.id, Match.stage == "swiss", Match.round_no == current
    ).order_by(Match.match_no)).all()
    if not rows:
        raise ValueError("Swiss-тур еще не сформирован")

    original = [cid for m in rows for cid in (m.red_cp_id, m.blue_cp_id)]
    allowed = [cid for cid in original if cid]
    supplied = [cid for cid in cp_ids if cid]
    if len(supplied) != len(set(supplied)) or set(supplied) != set(allowed):
        raise ValueError("Можно только переставлять участников текущего тура")
    slot_count = len(rows) * 2
    slots = list(cp_ids[:slot_count]) + [None] * max(0, slot_count - len(cp_ids))

    locked_slots: set[int] = set()
    for idx, m in enumerate(rows):
        if _layout_match_locked(m):
            locked_slots.update((idx * 2, idx * 2 + 1))
    for idx in locked_slots:
        if slots[idx] != original[idx]:
            cp_id = original[idx]
            cp = db.get(CategoryParticipant, cp_id) if cp_id else None
            name = cp.participant.display_name if cp else "Участник"
            raise ValueError(f"{name}: пару нельзя менять после начала боя")

    round_started = any(m.status != "staged" for m in rows)
    for idx, m in enumerate(rows):
        if idx * 2 in locked_slots:
            continue
        m.red_cp_id = slots[idx * 2]
        m.blue_cp_id = slots[idx * 2 + 1]
        if not m.red_cp_id and m.blue_cp_id:
            m.red_cp_id, m.blue_cp_id = m.blue_cp_id, None
        m.red_score = m.blue_score = 0
        m.red_warnings = m.blue_warnings = 0
        m.winner_cp_id = None
        m.result_reason = ""
        m.finished_at = None
        m.started_at = None
        m.timer_running = False
        m.timer_started_at = None
        m.remaining_ms = m.duration_ms
        m.timer_revision += 1
        m.version += 1
        if round_started:
            if m.red_cp_id and m.blue_cp_id:
                m.status = "ready"
            elif m.red_cp_id or m.blue_cp_id:
                m.status = "finished"
                m.winner_cp_id = m.red_cp_id or m.blue_cp_id
                m.result_reason = "BYE"
                m.finished_at = now_utc()
                for area in db.scalars(select(Area).where(Area.current_match_id == m.id)).all():
                    area.current_match_id = None
                m.area_id = None
                m.queue_order = 0
            else:
                m.status = "blocked"
        else:
            m.status = "staged"
    if round_started:
        auto_assign_ready_matches(db, category.tournament_id)
    audit(db, category.tournament_id, "SWISS_ROUND_REARRANGED", "category", category.id, payload={"round": current, "after_start": round_started})
    db.commit()
    return rows

def start_swiss_round(db: Session, category: Category) -> list[Match]:
    current = swiss_current_round(db, category.id)
    if not current:
        raise ValueError("Сначала сформируйте Swiss-тур")
    rows = db.scalars(select(Match).where(
        Match.category_id == category.id, Match.stage == "swiss", Match.round_no == current
    ).order_by(Match.match_no)).all()
    if not rows or any(m.status != "staged" for m in rows):
        raise ValueError("Текущий Swiss-тур уже начат")
    for m in rows:
        if m.red_cp_id and m.blue_cp_id:
            m.status = "ready"
        elif m.red_cp_id or m.blue_cp_id:
            m.winner_cp_id = m.red_cp_id or m.blue_cp_id
            m.status = "finished"
            m.result_reason = "BYE"
            m.finished_at = now_utc()
        else:
            m.status = "blocked"
    category.bracket_locked = True
    db.flush()
    auto_assign_ready_matches(db, category.tournament_id)
    audit(db, category.tournament_id, "SWISS_ROUND_STARTED", "category", category.id, payload={"round": current})
    db.commit()
    return rows
