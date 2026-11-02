"""Общее планирование нескольких площадок по загрузке и отдыху участников.

Уже выбранные/идущие бои и ранее назначенные блоки могут служить
неподвижной частью очереди. Для остальных планируется приблизительное
время по порядку очередей: при равных длительностях загрузка распределяется
поровну, а внутри каждой временной позиции снижаются пересечения бойцов.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..models import Match
from .common import _match_participant_ids


def _duration(match: Match) -> int:
    """Оценка занятости площадки; нулевая длительность не даёт нулевой вес."""
    return max(1, int(match.duration_ms or 0))


def _eligible_matches(remaining: list[Match]) -> list[Match]:
    """Не переносит более поздний круг той же стадии раньше предыдущего."""
    # Будущие pending-бои нельзя ставить перед доступными для проведения:
    # они могут содержать незаполненные слоты сетки.
    ready = [m for m in remaining if m.status == "ready"]
    candidates = ready if ready else remaining
    earliest: dict[tuple[int, str, str], int] = {}
    for match in candidates:
        key = (match.category_id, match.stage, match.group_name or "")
        earliest[key] = min(match.round_no, earliest.get(key, match.round_no))
    return [m for m in candidates if m.round_no == earliest[(m.category_id, m.stage, m.group_name or "")]]


def plan_balanced_queues(
    base_queues: Mapping[int, list[Match]],
    matches: list[Match],
    *,
    gap: int,
    avoid_consecutive: bool,
    recent_by_area: Mapping[int, list[set[int]]] | None = None,
) -> dict[int, list[Match]]:
    """Возвращает очереди с неизменяемым префиксом из ``base_queues``.

    Сначала выбирается менее загруженная площадка, поэтому конфликты не могут
    привести к сильному перекосу. Затем из допустимых по кругу боёв выбирается
    тот, для которого минимальны повторные выходы и межплощадочные пересечения.
    Решение детерминировано и не меняет исходные объекты до вызова клиента.
    """
    queues = {area_id: list(queue) for area_id, queue in sorted(base_queues.items())}
    if not queues:
        return queues
    gap = max(1, min(int(gap or 1), 10))
    histories = recent_by_area or {}
    loads = {area_id: sum(_duration(m) for m in queue) for area_id, queue in queues.items()}
    original_pos = {match.id: index for index, match in enumerate(matches)}
    remaining = list(matches)
    average_duration = max(1, sum(_duration(m) for queue in queues.values() for m in queue)
                           + sum(_duration(m) for m in remaining)) / max(1, sum(map(len, queues.values())) + len(remaining))
    people = {m.id: _match_participant_ids(m) for queue in queues.values() for m in queue}
    people.update({m.id: _match_participant_ids(m) for m in remaining})

    while remaining:
        # Число боёв — основной критерий; длительность уточняет выбор площадки.
        # При равных длительностях длины очередей различаются не более чем на 1.
        area_id = min(queues, key=lambda a: (len(queues[a]), loads[a] / average_duration, a))
        queue = queues[area_id]
        slot = len(queue)
        active_people = [people[m.id] for m in queue]
        local_history = list(histories.get(area_id, [])) + active_people

        def penalty(match: Match) -> tuple[int, int, int, int]:
            pids = people[match.id]
            local = 0
            if avoid_consecutive:
                for distance, prev in enumerate(reversed(local_history[-gap:]), 1):
                    if pids & prev:
                        local += gap - distance + 1
            cross = 0
            for other_id, other_queue in queues.items():
                if other_id == area_id:
                    continue
                for other_slot in range(max(0, slot - 1), min(len(other_queue), slot + 2)):
                    if pids & people[other_queue[other_slot].id]:
                        cross += 2 if other_slot == slot else 1
            return (cross * 100 + local * 10, original_pos[match.id], match.match_no, match.id)

        best = min(_eligible_matches(remaining), key=penalty)
        queue.append(best)
        loads[area_id] += _duration(best)
        remaining.remove(best)
    return queues


def queue_conflicts(queues: Mapping[int, list[Match]], gap: int) -> tuple[int, int]:
    """Число локальных повторов и уникальных межплощадочных конфликтов."""
    from .scheduling import cross_area_repeat_warnings, queue_repeat_warnings

    local = sum(len(queue_repeat_warnings(queue, gap)) for queue in queues.values())
    cross = cross_area_repeat_warnings(dict(queues))
    return local, sum(map(len, cross.values())) // 2
