"""Общие предметные функции, сериализация и аудит."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import Area, AuditEvent, Category, CategoryParticipant, Match, MatchEvent

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def json_load(value: str, fallback):
    """Безопасно читает JSON из БД и возвращает fallback для повреждённого значения."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback

def cp_label(cp: CategoryParticipant | None) -> dict[str, Any] | None:
    if not cp:
        return None
    p = cp.participant
    return {
        "cp_id": cp.id,
        "participant_id": p.id,
        "name": p.display_name,
        "club": p.club,
        "city": p.city,
        "warnings": cp.cumulative_warnings,
        "disqualified": cp.disqualified,
        "group": cp.group_name,
        "participant_status": p.status,
    }

def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()

def _affiliation_penalty(a: CategoryParticipant, b: CategoryParticipant, club_weight: int = 1000, city_weight: int = 100) -> int:
    """Чем выше штраф, тем дальше друг от друга желательно развести участников."""
    penalty = 0
    if _norm(a.participant.club) and _norm(a.participant.club) == _norm(b.participant.club):
        penalty += club_weight
    if _norm(a.participant.city) and _norm(a.participant.city) == _norm(b.participant.city):
        penalty += city_weight
    return penalty

def _match_participant_ids(match: Match) -> set[int]:
    """Возвращает ID людей, чтобы один участник распознавался между категориями."""
    ids: set[int] = set()
    if match.red_cp is not None:
        ids.add(match.red_cp.participant_id)
    if match.blue_cp is not None:
        ids.add(match.blue_cp.participant_id)
    return ids

def effective_remaining_ms(match: Match) -> int:
    if not match.timer_running or not match.timer_started_at:
        return max(0, match.remaining_ms)
    started = match.timer_started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = int((now_utc() - started).total_seconds() * 1000)
    return max(0, match.remaining_ms - elapsed)

def match_dict(match: Match) -> dict[str, Any]:
    remaining = effective_remaining_ms(match)
    return {
        "id": match.id,
        "category_id": match.category_id,
        "category_name": match.category.name,
        "category_format": match.category.format,
        "stage": match.stage,
        "round_no": match.round_no,
        "match_no": match.match_no,
        "group_name": match.group_name,
        "is_third_place": bool(match.is_third_place),
        "red": cp_label(match.red_cp),
        "blue": cp_label(match.blue_cp),
        "red_score": match.red_score,
        "blue_score": match.blue_score,
        "red_warnings": match.red_warnings,
        "blue_warnings": match.blue_warnings,
        "winner_cp_id": match.winner_cp_id,
        "reason": match.result_reason,
        "status": match.status,
        "area_id": match.area_id,
        "queue_order": match.queue_order,
        "duration_ms": match.duration_ms,
        "remaining_ms": remaining,
        "timer_running": bool(match.timer_running and remaining > 0),
        "timer_started_at": match.timer_started_at.isoformat() if match.timer_started_at else None,
        "timer_revision": match.timer_revision,
        "version": match.version,
        "score_buttons": json_load(match.category.score_buttons_json, []),
        "warning_rules": json_load(match.category.warning_rules_json, []),
        "timer_warning_sec": match.category.timer_warning_sec,
        "next_match_id": match.next_match_id,
        "next_slot": match.next_slot,
    }

def category_dict(category: Category) -> dict[str, Any]:
    return {
        "id": category.id,
        "tournament_id": category.tournament_id,
        "name": category.name,
        "format": category.format,
        "match_duration_sec": category.match_duration_sec,
        "timer_warning_sec": category.timer_warning_sec,
        "score_buttons": json_load(category.score_buttons_json, []),
        "warning_rules": json_load(category.warning_rules_json, []),
        "cumulative_warning_limit": category.cumulative_warning_limit,
        "group_target_size": category.group_target_size,
        "group_qualifiers": category.group_qualifiers,
        "swiss_rounds": category.swiss_rounds,
        "win_points": category.win_points,
        "draw_points": category.draw_points,
        "status": category.status,
        "bracket_locked": category.bracket_locked,
        "completed_at": category.completed_at.isoformat() if category.completed_at else None,
    }

def audit(db: Session, tournament_id: int | None, event_type: str, entity_type: str = "", entity_id: int | None = None,
          area_id: int | None = None, payload: dict | None = None) -> None:
    db.add(AuditEvent(
        tournament_id=tournament_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        area_id=area_id,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
    ))

def clear_category_matches(db: Session, category: Category) -> None:
    active = db.scalar(select(func.count(Match.id)).where(Match.category_id == category.id, ((Match.status == "in_progress") | ((Match.status == "finished") & (Match.result_reason != "BYE")))))
    if active:
        raise ValueError("Нельзя перестроить сетку после начала поединков категории")
    area_ids = db.scalars(select(Area.id).where(Area.current_match_id.in_(select(Match.id).where(Match.category_id == category.id)))).all()
    for area_id in area_ids:
        area = db.get(Area, area_id)
        if area:
            area.current_match_id = None
    db.execute(delete(MatchEvent).where(MatchEvent.match_id.in_(select(Match.id).where(Match.category_id == category.id))))
    db.execute(delete(Match).where(Match.category_id == category.id))
    db.flush()

def add_category_participant(db: Session, category_id: int, participant_id: int) -> CategoryParticipant:
    existing = db.scalar(select(CategoryParticipant).where(
        CategoryParticipant.category_id == category_id,
        CategoryParticipant.participant_id == participant_id,
    ))
    if existing:
        return existing
    max_seed = db.scalar(select(func.max(CategoryParticipant.seed_order)).where(CategoryParticipant.category_id == category_id)) or 0
    cp = CategoryParticipant(category_id=category_id, participant_id=participant_id, seed_order=max_seed + 1)
    db.add(cp)
    db.flush()
    return cp

def _layout_match_locked(match: Match) -> bool:
    """Бой нельзя безопасно переставлять после начала любой реальной активности."""
    return bool(
        match.status == "in_progress"
        or (match.status == "finished" and match.result_reason != "BYE")
        or match.started_at is not None
        or match.red_score
        or match.blue_score
        or match.red_warnings
        or match.blue_warnings
    )

def _real_match_started(match: Match) -> bool:
    return match.status == "in_progress" or (match.status == "finished" and match.result_reason != "BYE")

def _delete_match_rows(db: Session, rows: list[Match]) -> None:
    ids = [m.id for m in rows]
    if not ids:
        return
    for area in db.scalars(select(Area).where(Area.current_match_id.in_(ids))).all():
        area.current_match_id = None
    db.execute(delete(MatchEvent).where(MatchEvent.match_id.in_(ids)))
    db.execute(delete(Match).where(Match.id.in_(ids)))
    db.flush()
