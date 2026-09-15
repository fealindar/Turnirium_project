"""Назначение поединков на площадки и оптимизация очередей."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Area, Category, Match, Tournament
from .common import _match_participant_ids

def _best_effort_match_order(matches: list[Match], recent_sets: list[set[int]], gap: int) -> list[Match]:
    """Жадно упорядочивает очередь, избегая повторных выходов при наличии альтернатив.

    ``gap`` — желаемое число других боёв между двумя выходами одного участника.
    Ограничение мягкое: при конфликте всех вариантов выбирается наименее плохой
    и наиболее ранний исходный бой.
    """
    if not matches:
        return []
    gap = max(1, min(int(gap or 1), 10))
    remaining = list(matches)
    original_pos = {m.id: i for i, m in enumerate(remaining)}
    history = list(recent_sets[-gap:])
    ordered: list[Match] = []
    while remaining:
        best = None
        best_key = None
        for m in remaining:
            pids = _match_participant_ids(m)
            penalty = 0
            # Самый свежий конфликт наиболее критичен; более старые конфликты
            # внутри желаемого интервала учитываются с меньшим весом.
            for distance, previous in enumerate(reversed(history), 1):
                if pids & previous:
                    penalty += (gap - distance + 1) * 10000
            key = (penalty, original_pos[m.id], m.category_id, m.match_no, m.id)
            if best_key is None or key < best_key:
                best, best_key = m, key
        ordered.append(best)
        remaining.remove(best)
        history.append(_match_participant_ids(best))
        history = history[-gap:]
    return ordered

def optimize_area_queue(db: Session, area: Area) -> int:
    """Оптимизирует незапущенную очередь площадки и возвращает число предупреждений."""
    tournament = db.get(Tournament, area.tournament_id)
    if not tournament or not tournament.avoid_consecutive_matches:
        return 0
    gap = max(1, min(int(tournament.preferred_match_gap or 1), 10))
    current = db.get(Match, area.current_match_id) if area.current_match_id else None
    candidates = db.scalars(
        select(Match).where(
            Match.area_id == area.id,
            Match.status.in_(["ready", "pending"]),
            Match.id != area.current_match_id,
        ).order_by(Match.queue_order, Match.id)
    ).all()
    history: list[set[int]] = []
    if current and current.status != "finished":
        history.append(_match_participant_ids(current))
    else:
        recent_finished = db.scalars(
            select(Match).where(Match.area_id == area.id, Match.status == "finished").order_by(Match.finished_at.desc(), Match.id.desc()).limit(gap)
        ).all()
        history = [_match_participant_ids(m) for m in reversed(recent_finished)]
    ordered = _best_effort_match_order(candidates, history, gap)
    order = 1
    if current and current.status != "finished":
        current.queue_order = order
        order += 1
    for m in ordered:
        m.queue_order = order
        order += 1
    db.flush()

    # Считаем неизбежные близкие повторные выходы для предупреждения организатору.
    warnings = 0
    seq = ([current] if current and current.status != "finished" else []) + ordered
    recent: list[set[int]] = []
    for m in seq:
        pids = _match_participant_ids(m)
        if any(pids & prev for prev in recent[-gap:]):
            warnings += 1
        recent.append(pids)
    return warnings

def auto_assign_ready_matches(db: Session, tournament_id: int) -> None:
    """Автоматически назначает бои, если в турнире включена одна площадка.

    Новые бои упорядочиваются с максимально возможным отдыхом, а уже заданный
    организатором ручной порядок остаётся неизменным.
    """
    areas = db.scalars(select(Area).where(Area.tournament_id == tournament_id, Area.enabled.is_(True)).order_by(Area.id)).all()
    if len(areas) != 1:
        return
    area = areas[0]
    tournament = db.get(Tournament, tournament_id)
    max_order = db.scalar(select(func.max(Match.queue_order)).where(Match.area_id == area.id)) or 0
    unassigned = db.scalars(
        select(Match).join(Category).join(Tournament, Category.tournament_id == Tournament.id).where(
            Category.tournament_id == tournament_id,
            Category.status != "completed",
            Tournament.status != "completed",
            Match.area_id.is_(None),
            Match.status.in_(["ready", "pending"]),
        ).order_by(Match.category_id, Match.match_no)
    ).all()

    ordered_new = list(unassigned)
    if unassigned and tournament and tournament.avoid_consecutive_matches:
        gap = max(1, min(int(tournament.preferred_match_gap or 1), 10))
        existing = db.scalars(
            select(Match).where(
                Match.area_id == area.id,
                Match.status.in_(["ready", "pending", "in_progress"]),
            ).order_by(Match.queue_order, Match.id)
        ).all()
        recent = [_match_participant_ids(m) for m in existing[-gap:]]
        ordered_new = _best_effort_match_order(unassigned, recent, gap)

    for m in ordered_new:
        max_order += 1
        m.area_id = area.id
        m.queue_order = max_order
    db.flush()
    if area.current_match_id is None:
        first = db.scalar(
            select(Match).join(Category).join(Tournament, Category.tournament_id == Tournament.id).where(
                Match.area_id == area.id,
                Category.status != "completed",
                Tournament.status != "completed",
                Match.status.in_(["ready", "pending"]),
            ).order_by(Match.queue_order, Match.id)
        )
        if first:
            area.current_match_id = first.id

def cross_area_repeat_warnings(
    queues: dict[int, list[Match]],
    distance: int = 1,
) -> dict[int, set[int]]:
    """Находит близкие выходы одного бойца на разных площадках.

    Позиции сравниваются внутри активных очередей площадок. ``distance=1``
    означает конфликт на той же позиции либо на соседней позиции очереди.
    Возвращается двусторонняя карта ``бой -> конфликтующие бои``.
    """
    distance = max(0, min(int(distance), 10))
    area_ids = sorted(queues)
    conflicts: dict[int, set[int]] = {}
    for left_index, left_area_id in enumerate(area_ids):
        left_queue = queues[left_area_id]
        for right_area_id in area_ids[left_index + 1:]:
            right_queue = queues[right_area_id]
            for left_pos, left_match in enumerate(left_queue):
                left_people = _match_participant_ids(left_match)
                if not left_people:
                    continue
                start = max(0, left_pos - distance)
                stop = min(len(right_queue), left_pos + distance + 1)
                for right_match in right_queue[start:stop]:
                    if left_people & _match_participant_ids(right_match):
                        conflicts.setdefault(left_match.id, set()).add(right_match.id)
                        conflicts.setdefault(right_match.id, set()).add(left_match.id)
    return conflicts

def assign_ready_category_unit(
    db: Session,
    tournament_id: int,
    category_id: int,
    area_id: int,
    group_name: str = "",
) -> int:
    """Назначает на площадку все готовые бои категории или одной группы.

    Будущие ``pending``-бои плей-офф не переносятся: их участники ещё не
    определены. Уже назначенные, начатые и завершённые поединки также остаются
    на своих местах. Новые бои добавляются в конец очереди и затем, если это
    разрешено настройками турнира, очередь мягко оптимизируется по отдыху.
    """
    area = db.get(Area, area_id)
    category = db.get(Category, category_id)
    if not area or area.tournament_id != tournament_id:
        raise ValueError("Площадка не относится к выбранному турниру")
    if not area.enabled:
        raise ValueError("Нельзя назначить бои на отключенную площадку")
    if not category or category.tournament_id != tournament_id:
        raise ValueError("Категория не относится к выбранному турниру")

    filters = [
        Match.category_id == category_id,
        Match.area_id.is_(None),
        Match.status == "ready",
    ]
    if group_name:
        filters.append(Match.stage == "group")
        filters.append(Match.group_name == group_name)

    matches = db.scalars(
        select(Match).where(*filters).order_by(Match.group_name, Match.match_no, Match.id)
    ).all()
    if not matches:
        return 0

    max_order = db.scalar(
        select(func.max(Match.queue_order)).where(Match.area_id == area_id)
    ) or 0
    for match in matches:
        max_order += 1
        match.area_id = area_id
        match.queue_order = max_order
    db.flush()

    tournament = db.get(Tournament, tournament_id)
    if tournament and tournament.avoid_consecutive_matches:
        optimize_area_queue(db, area)
    return len(matches)

def queue_repeat_warnings(matches: list[Match], gap: int) -> set[int]:
    """Возвращает ID боёв, расположенных ближе желаемого к предыдущему выходу участника."""
    gap = max(1, min(int(gap or 1), 10))
    recent: list[set[int]] = []
    warned: set[int] = set()
    for m in matches:
        pids = _match_participant_ids(m)
        if any(pids & prev for prev in recent[-gap:]):
            warned.add(m.id)
        recent.append(pids)
    return warned
