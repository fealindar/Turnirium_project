"""Управление HTTP расписанием и очередями площадок."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..engine import (
    audit,
    auto_assign_ready_matches,
    match_dict,
    optimize_area_queue,
    queue_repeat_warnings,
)
from ..models import Area, Category, Match, Tournament
from .common import _broadcast, _get_or_404
from .schemas import AssignIn, ReorderIn, ScheduleSettingsIn

router = APIRouter()


def _active_area_matches(db: Session, tournament_id: int, area_id: int) -> list[Match]:
    """Возвращает незавершённую очередь площадки только из активных категорий."""

    return db.scalars(
        select(Match)
        .join(Category)
        .where(
            Category.tournament_id == tournament_id,
            Category.status != "completed",
            Match.area_id == area_id,
            Match.status != "finished",
        )
        .order_by(Match.queue_order, Match.id)
    ).all()


def _clear_current_area_reference(db: Session, match_id: int) -> None:
    """Убирает бой из поля current_match_id перед переносом на другую площадку."""

    areas = db.scalars(select(Area).where(Area.current_match_id == match_id)).all()
    for area in areas:
        area.current_match_id = None


@router.get("/tournaments/{tournament_id}/schedule")
def schedule(tournament_id: int, db: Session = Depends(get_db)):
    """Возвращает очереди площадок и автоматически назначает новые готовые бои."""

    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")

    # Старые турниры также получают режим одной площадки без ручной настройки
    # сразу после открытия организатором расписания или панели управления.
    auto_assign_ready_matches(db, tournament_id)
    db.commit()

    areas = db.scalars(
        select(Area).where(Area.tournament_id == tournament_id).order_by(Area.id)
    ).all()

    area_rows: list[dict] = []
    for area in areas:
        matches = _active_area_matches(db, tournament_id, area.id)
        warned = (
            queue_repeat_warnings(matches, tournament.preferred_match_gap)
            if tournament.avoid_consecutive_matches
            else set()
        )
        payload = []
        for match in matches:
            item = match_dict(match)
            item["repeat_warning"] = match.id in warned
            payload.append(item)
        area_rows.append(
            {
                "area": {
                    "id": area.id,
                    "name": area.name,
                    "current_match_id": area.current_match_id,
                },
                "matches": payload,
            }
        )

    unassigned = db.scalars(
        select(Match)
        .join(Category)
        .where(
            Category.tournament_id == tournament_id,
            Category.status != "completed",
            Match.area_id.is_(None),
            Match.status == "ready",
        )
        .order_by(Match.category_id, Match.match_no)
    ).all()

    return {
        "areas": area_rows,
        "unassigned": [match_dict(match) for match in unassigned],
        "settings": {
            "avoid_consecutive_matches": bool(tournament.avoid_consecutive_matches),
            "preferred_match_gap": int(tournament.preferred_match_gap or 1),
        },
    }


@router.put("/tournaments/{tournament_id}/schedule-settings")
async def update_schedule_settings(
    tournament_id: int,
    data: ScheduleSettingsIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Изменяет правила автоматического разведения повторных выходов."""

    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    tournament.avoid_consecutive_matches = bool(data.avoid_consecutive_matches)
    tournament.preferred_match_gap = max(1, min(int(data.preferred_match_gap), 10))
    audit(
        db,
        tournament.id,
        "SCHEDULE_SETTINGS_CHANGED",
        "tournament",
        tournament.id,
        payload={
            "avoid_consecutive_matches": tournament.avoid_consecutive_matches,
            "preferred_match_gap": tournament.preferred_match_gap,
        },
    )
    db.commit()
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": tournament.id},
    )
    return {
        "ok": True,
        "avoid_consecutive_matches": tournament.avoid_consecutive_matches,
        "preferred_match_gap": tournament.preferred_match_gap,
    }


@router.post("/tournaments/{tournament_id}/schedule-optimize")
async def optimize_schedule(
    tournament_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Перестраивает очереди всех включённых площадок с учётом отдыха бойцов."""

    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    if not tournament.avoid_consecutive_matches:
        raise HTTPException(409, "Сначала включите разведение повторных выходов")

    areas = db.scalars(
        select(Area)
        .where(Area.tournament_id == tournament.id, Area.enabled.is_(True))
        .order_by(Area.id)
    ).all()
    warnings = sum(optimize_area_queue(db, area) for area in areas)
    audit(
        db,
        tournament.id,
        "SCHEDULE_OPTIMIZED",
        "tournament",
        tournament.id,
        payload={
            "preferred_match_gap": tournament.preferred_match_gap,
            "unavoidable_conflicts": warnings,
        },
    )
    db.commit()
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": tournament.id},
    )
    return {"ok": True, "unavoidable_conflicts": warnings}


@router.post("/schedule/assign")
async def assign_match(
    data: AssignIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Назначает ещё не начатый бой на площадку либо снимает назначение."""

    match = _get_or_404(db, Match, data.match_id, "Поединок")
    if match.status in {"in_progress", "finished"}:
        raise HTTPException(409, "Начатый или завершенный бой нельзя переназначить")

    target_area: Area | None = None
    if data.area_id is not None:
        target_area = _get_or_404(db, Area, data.area_id, "Площадка")
        if target_area.tournament_id != match.category.tournament_id:
            raise HTTPException(400, "Площадка из другого турнира")

    # Если бой уже выбран текущим на прежней площадке, перенос не должен оставлять
    # там устаревшую ссылку на бой, который фактически находится в другой очереди.
    if data.area_id != match.area_id:
        _clear_current_area_reference(db, match.id)

    if target_area is None:
        match.area_id = None
        match.queue_order = 0
    else:
        match.area_id = target_area.id
        if data.position is not None:
            match.queue_order = data.position
        else:
            last_position = db.scalar(
                select(func.max(Match.queue_order)).where(Match.area_id == target_area.id)
            ) or 0
            match.queue_order = last_position + 1

    db.commit()
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": match.category.tournament_id},
    )
    return {"ok": True}


@router.put("/areas/{area_id}/queue")
async def reorder_area(
    area_id: int,
    data: ReorderIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Изменяет порядок незавершённых боёв одной площадки."""

    area = _get_or_404(db, Area, area_id, "Площадка")
    if len(data.match_ids) != len(set(data.match_ids)):
        raise HTTPException(400, "Очередь содержит повторяющиеся поединки")

    matches = {
        match.id: match
        for match in db.scalars(
            select(Match).where(Match.area_id == area_id, Match.status != "finished")
        ).all()
    }
    unknown = [match_id for match_id in data.match_ids if match_id not in matches]
    if unknown:
        raise HTTPException(400, "Очередь содержит бой, не назначенный на эту площадку")

    ordered_ids = list(data.match_ids)
    ordered_ids.extend(match_id for match_id in matches if match_id not in set(ordered_ids))
    for position, match_id in enumerate(ordered_ids, 1):
        match = matches[match_id]
        if match.status == "in_progress" and match_id != area.current_match_id:
            continue
        match.queue_order = position

    db.commit()
    await _broadcast(
        request,
        {
            "type": "schedule_changed",
            "tournament_id": area.tournament_id,
            "area_id": area_id,
        },
    )
    return {"ok": True}


@router.post("/areas/{area_id}/select/{match_id}")
async def select_match(
    area_id: int,
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Выбирает текущий бой площадки без обхода незавершённого предыдущего боя."""

    area = _get_or_404(db, Area, area_id, "Площадка")
    match = _get_or_404(db, Match, match_id, "Поединок")
    if match.area_id != area_id:
        raise HTTPException(409, "Бой не назначен на эту площадку")
    if match.status in {"staged", "blocked", "finished"}:
        raise HTTPException(409, "Этот бой нельзя выбрать текущим")

    current = db.get(Match, area.current_match_id) if area.current_match_id else None
    if current and current.id != match.id and current.status != "finished":
        raise HTTPException(409, "Сначала внесите результат текущего боя")

    area.current_match_id = match.id
    db.commit()
    await _broadcast(
        request,
        {"type": "area_changed", "area_id": area_id, "match_id": match.id},
    )
    return match_dict(match)


@router.post("/areas/{area_id}/next")
async def select_next(area_id: int, request: Request, db: Session = Depends(get_db)):
    """Переходит к следующему бою только после сохранения результата текущего."""

    area = _get_or_404(db, Area, area_id, "Площадка")
    current = db.get(Match, area.current_match_id) if area.current_match_id else None
    if current is not None and current.status != "finished":
        raise HTTPException(409, "Сначала внесите результат текущего боя")

    next_match = db.scalar(
        select(Match)
        .where(
            Match.area_id == area_id,
            Match.status.in_(["ready", "pending"]),
            Match.id != area.current_match_id,
        )
        .order_by(Match.queue_order, Match.id)
    )
    if not next_match:
        raise HTTPException(404, "В очереди нет следующего готового поединка")

    area.current_match_id = next_match.id
    db.commit()
    await _broadcast(
        request,
        {"type": "area_changed", "area_id": area_id, "match_id": next_match.id},
    )
    return match_dict(next_match)


@router.get("/areas/{area_id}/state")
def area_state(area_id: int, db: Session = Depends(get_db)):
    """Возвращает текущий бой и ближайшие позиции очереди секретарю площадки."""

    area = _get_or_404(db, Area, area_id, "Площадка")
    current = db.get(Match, area.current_match_id) if area.current_match_id else None
    queue = db.scalars(
        select(Match)
        .join(Category)
        .where(
            Match.area_id == area_id,
            Category.status != "completed",
            Match.status.in_(["ready", "pending", "in_progress"]),
            Match.id != area.current_match_id,
        )
        .order_by(Match.queue_order, Match.id)
    ).all()
    return {
        "area": {"id": area.id, "name": area.name},
        "current": match_dict(current) if current else None,
        "next": match_dict(queue[0]) if queue else None,
        "following": match_dict(queue[1]) if len(queue) > 1 else None,
        "queue": [match_dict(match) for match in queue],
    }
