"""Ручное распределение категории или группы на выбранные площадки."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Area, Category, Match, Tournament
from .schedule_balancer import plan_balanced_queues
from .scheduling import assign_ready_category_unit


def distribute_category_unit(
    db: Session,
    tournament_id: int,
    category_id: int,
    area_ids: list[int],
    group_name: str = "",
) -> dict[int, int]:
    """Распределяет только готовые неназначенные бои, не перемещая другие."""
    if not area_ids or len(area_ids) != len(set(area_ids)):
        raise ValueError("Выберите одну или несколько уникальных площадок")
    areas = db.scalars(select(Area).where(Area.id.in_(area_ids))).all()
    if len(areas) != len(area_ids) or any(a.tournament_id != tournament_id or not a.enabled for a in areas):
        raise ValueError("Все выбранные площадки должны быть включены в выбранном турнире")
    category = db.get(Category, category_id)
    if not category or category.tournament_id != tournament_id or category.status == "completed":
        raise ValueError("Категория недоступна для распределения")
    if group_name and category.format != "groups":
        raise ValueError("Выбор группы допустим только в групповом формате")
    tournament = db.get(Tournament, tournament_id)
    if not tournament or tournament.status == "completed":
        raise ValueError("Турнир завершён")

    # Один выбор должен в точности повторять прежнее быстрое назначение:
    # очередность, мягкая оптимизация и проверки остаются общими для API и UI.
    if len(area_ids) == 1:
        count = assign_ready_category_unit(db, tournament_id, category_id, area_ids[0], group_name)
        return {area_ids[0]: count} if count else {}

    filters = [Match.category_id == category_id, Match.area_id.is_(None), Match.status == "ready"]
    if group_name:
        filters += [Match.stage == "group", Match.group_name == group_name]
    matches = db.scalars(select(Match).where(*filters).order_by(
        Match.round_no, Match.match_no, Match.id
    )).all()
    if not matches:
        return {}

    base = {
        area.id: db.scalars(select(Match).join(Category).where(
            Match.area_id == area.id,
            Category.status != "completed",
            Match.status.in_(["ready", "pending", "in_progress"]),
        ).order_by(Match.queue_order, Match.id)).all()
        for area in areas
    }
    planned = plan_balanced_queues(
        base, matches, gap=tournament.preferred_match_gap,
        avoid_consecutive=tournament.avoid_consecutive_matches,
    )
    counts: dict[int, int] = {}
    for area in areas:
        preserved = len(base[area.id])
        new_matches = planned[area.id][preserved:]
        max_order = db.scalar(select(func.max(Match.queue_order)).where(Match.area_id == area.id)) or 0
        for match in new_matches:
            max_order += 1
            match.area_id = area.id
            match.queue_order = max_order
        if new_matches:
            counts[area.id] = len(new_matches)
    db.flush()
    return counts
