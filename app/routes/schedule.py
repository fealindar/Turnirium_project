"""Управление HTTP расписанием и очередями площадок."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..engine import (
    assign_ready_category_unit,
    audit,
    auto_assign_ready_matches,
    cross_area_repeat_warnings,
    match_dict,
    optimize_area_queue,
    queue_repeat_warnings,
)
from ..models import Area, Category, CategoryParticipant, Match, Tournament
from .common import _broadcast, _get_or_404
from .schemas import AssignIn, ReorderIn, ScheduleSettingsIn, ScheduleUnitAssignIn

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


def _schedule_category_units(db: Session, tournament_id: int) -> list[dict]:
    """Готовит категории и группы для панели быстрого назначения."""

    categories = db.scalars(
        select(Category).where(
            Category.tournament_id == tournament_id,
            Category.status != "completed",
        ).order_by(Category.id)
    ).all()
    result: list[dict] = []
    for category in categories:
        participants = db.scalars(
            select(CategoryParticipant).where(
                CategoryParticipant.category_id == category.id,
                CategoryParticipant.disqualified.is_(False),
            ).order_by(CategoryParticipant.seed_order, CategoryParticipant.id)
        ).all()
        active = [
            cp for cp in participants
            if cp.participant.active and cp.participant.status != "withdrawn"
        ]
        if not active:
            continue
        matches = db.scalars(
            select(Match).where(
                Match.category_id == category.id,
                Match.status != "finished",
            ).order_by(Match.match_no, Match.id)
        ).all()
        groups: list[dict] = []
        group_names = sorted({cp.group_name for cp in active if cp.group_name})
        for group_name in group_names:
            group_people = [cp for cp in active if cp.group_name == group_name]
            group_matches = [m for m in matches if m.stage == "group" and m.group_name == group_name]
            groups.append({
                "name": group_name,
                "participant_count": len(group_people),
                "participants": [cp.participant.display_name for cp in group_people],
                "ready_unassigned": sum(
                    m.area_id is None and m.status == "ready" for m in group_matches
                ),
                "assigned_open": sum(m.area_id is not None for m in group_matches),
            })
        result.append({
            "category_id": category.id,
            "name": category.name,
            "format": category.format,
            "participant_count": len(active),
            "participants": [cp.participant.display_name for cp in active],
            "ready_unassigned": sum(
                m.area_id is None and m.status == "ready" for m in matches
            ),
            "assigned_open": sum(m.area_id is not None for m in matches),
            "groups": groups,
        })
    return result


def _cross_warning_details(
    conflicts: dict[int, set[int]],
    matches: dict[int, Match],
    areas: dict[int, Area],
    positions: dict[int, int],
) -> dict[int, list[dict]]:
    """Преобразует межплощадочные конфликты в данные для интерфейса."""

    details: dict[int, list[dict]] = {}
    for match_id, other_ids in conflicts.items():
        current = matches.get(match_id)
        if not current:
            continue
        current_people = {
            cp.participant_id: cp.participant.display_name
            for cp in (current.red_cp, current.blue_cp) if cp
        }
        rows: list[dict] = []
        for other_id in sorted(other_ids):
            other = matches.get(other_id)
            if not other:
                continue
            other_people = {
                cp.participant_id: cp.participant.display_name
                for cp in (other.red_cp, other.blue_cp) if cp
            }
            shared = [current_people[pid] for pid in current_people.keys() & other_people.keys()]
            area = areas.get(other.area_id or 0)
            rows.append({
                "match_id": other.id,
                "area_id": other.area_id,
                "area_name": area.name if area else "Площадка",
                "queue_order": other.queue_order,
                "queue_position": positions.get(other.id, 0),
                "participants": shared,
                "category_name": other.category.name,
            })
        if rows:
            details[match_id] = rows
    return details


@router.get("/tournaments/{tournament_id}/schedule")
def schedule(tournament_id: int, db: Session = Depends(get_db)):
    """Возвращает очереди, быстрые назначения и предупреждения расписания."""

    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    auto_assign_ready_matches(db, tournament_id)
    db.commit()

    areas = db.scalars(
        select(Area).where(Area.tournament_id == tournament_id).order_by(Area.id)
    ).all()
    area_lookup = {area.id: area for area in areas}
    queues = {area.id: _active_area_matches(db, tournament_id, area.id) for area in areas}
    all_matches = {match.id: match for queue in queues.values() for match in queue}
    queue_positions = {
        match.id: position
        for queue in queues.values()
        for position, match in enumerate(queue, 1)
    }
    enabled_queues = {area.id: queues[area.id] for area in areas if area.enabled}
    cross_conflicts = cross_area_repeat_warnings(enabled_queues, distance=1)
    cross_details = _cross_warning_details(
        cross_conflicts, all_matches, area_lookup, queue_positions
    )

    area_rows: list[dict] = []
    for area in areas:
        matches = queues[area.id]
        warned = (
            queue_repeat_warnings(matches, tournament.preferred_match_gap)
            if tournament.avoid_consecutive_matches else set()
        )
        payload = []
        for position, match in enumerate(matches, 1):
            item = match_dict(match)
            item["queue_position"] = position
            item["repeat_warning"] = match.id in warned
            item["cross_area_warning"] = match.id in cross_details
            item["cross_area_conflicts"] = cross_details.get(match.id, [])
            payload.append(item)
        area_rows.append({
            "area": {
                "id": area.id,
                "name": area.name,
                "enabled": area.enabled,
                "current_match_id": area.current_match_id,
            },
            "matches": payload,
        })

    unassigned = db.scalars(
        select(Match).join(Category).where(
            Category.tournament_id == tournament_id,
            Category.status != "completed",
            Match.area_id.is_(None),
            Match.status == "ready",
        ).order_by(Match.category_id, Match.group_name, Match.match_no)
    ).all()
    return {
        "areas": area_rows,
        "unassigned": [match_dict(match) for match in unassigned],
        "category_units": _schedule_category_units(db, tournament_id),
        "settings": {
            "avoid_consecutive_matches": bool(tournament.avoid_consecutive_matches),
            "preferred_match_gap": int(tournament.preferred_match_gap or 1),
            "cross_area_distance": 1,
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


@router.post("/tournaments/{tournament_id}/schedule-reset")
async def reset_schedule_assignments(
    tournament_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Снимает распределение всех незавершённых боёв по площадкам."""

    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    active_matches = db.scalar(
        select(func.count(Match.id))
        .join(Category)
        .where(
            Category.tournament_id == tournament.id,
            Match.status == "in_progress",
        )
    ) or 0
    if active_matches:
        raise HTTPException(
            409,
            "Нельзя сбросить распределение, пока идёт хотя бы один бой.",
        )

    matches = db.scalars(
        select(Match)
        .join(Category)
        .where(
            Category.tournament_id == tournament.id,
            Match.status != "finished",
            Match.area_id.is_not(None),
        )
    ).all()
    for match in matches:
        match.area_id = None
        match.queue_order = 0

    areas = db.scalars(
        select(Area).where(Area.tournament_id == tournament.id)
    ).all()
    for area in areas:
        area.current_match_id = None

    audit(
        db,
        tournament.id,
        "SCHEDULE_RESET",
        "tournament",
        tournament.id,
        payload={"unassigned_matches": len(matches)},
    )
    db.commit()
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": tournament.id},
    )
    await _broadcast(
        request,
        {"type": "areas_changed", "tournament_id": tournament.id},
    )
    return {"ok": True, "unassigned_matches": len(matches)}


@router.post("/tournaments/{tournament_id}/schedule-assign-unit")
async def assign_schedule_unit(
    tournament_id: int,
    data: ScheduleUnitAssignIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Быстро назначает готовые бои категории или группы на площадку."""

    _get_or_404(db, Tournament, tournament_id, "Турнир")
    try:
        assigned = assign_ready_category_unit(
            db, tournament_id, data.category_id, data.area_id, data.group_name.strip()
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not assigned:
        raise HTTPException(409, "В выбранном блоке нет готовых неназначенных боёв")
    audit(
        db, tournament_id, "SCHEDULE_UNIT_ASSIGNED", "category", data.category_id,
        area_id=data.area_id,
        payload={"group_name": data.group_name.strip(), "assigned": assigned},
    )
    db.commit()
    await _broadcast(request, {"type": "schedule_changed", "tournament_id": tournament_id})
    return {"ok": True, "assigned": assigned}


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
        if not target_area.enabled:
            raise HTTPException(409, "Нельзя назначить бой на отключенную площадку")

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
