"""Посев группового плей-офф с учётом мест и исходных групп.

Здесь намеренно не используется жеребьёвка групп или разведение по клубам:
участники групп уже определены, а приоритет плей-офф — спортивный посев.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .brackets import next_power_of_two


@dataclass(frozen=True)
class _Qualifier:
    cp_id: int
    group: str
    place: int


def _seed_order(slots: int) -> list[int]:
    """Стандартная зеркальная сетка: 1 и 2 — в разных половинах,
    первые четыре — в разных четвертях и т.д.

    Смежные элементы — два соперника первого раунда. Неиспользованные
    номера посева (> числа вышедших участников) становятся BYE.
    """
    order = [1]
    while len(order) < slots:
        size = len(order) * 2
        order = [value for seed in order for value in (seed, size + 1 - seed)]
    return order


def _round_of_possible_meeting(pos_a: int, pos_b: int) -> int:
    # Слоты одной пары отличаются младшим битом; соседние пары внутри
    # четверти могут встретиться только во втором раунде и т.д.
    return (pos_a ^ pos_b).bit_length()


def _group_collision_cost(groups: list[str | None], rounds: int) -> tuple[int, ...]:
    """Число потенциальных повторных встреч в каждом раунде.

    Сравнение лексикографическое: отсутствие реваншей в первом раунде
    важнее любого количества потенциальных встреч в поздних раундах.
    """
    cost = [0] * rounds
    positions: dict[str, list[int]] = {}
    for pos, group in enumerate(groups):
        if group is None:
            continue
        previous = positions.setdefault(group, [])
        for other in previous:
            cost[_round_of_possible_meeting(pos, other) - 1] += 1
        previous.append(pos)
    return tuple(cost)


def _improve_group_spread(
    placed: list[_Qualifier | None],
) -> list[_Qualifier | None]:
    """Меняет местами только участников с одинаковым местом в группе.

    В результате стандартный посев и распределение BYE не нарушаются,
    но бойцы одной группы встречаются как можно позже. Перестановки
    детерминированы; каждый шаг строго улучшает оценку сетки.
    """
    rounds = (len(placed) - 1).bit_length()
    by_place: dict[int, list[int]] = {}
    by_group: dict[str, set[int]] = {}
    for pos, entrant in enumerate(placed):
        if entrant is None:
            continue
        by_place.setdefault(entrant.place, []).append(pos)
        by_group.setdefault(entrant.group, set()).add(pos)

    cost = _group_collision_cost(
        [entrant.group if entrant else None for entrant in placed], rounds
    )
    # Сначала устраняем ранние реванши. Для больших сеток ограничиваем
    # число локальных перестановок, иначе улучшение крайне поздних раундов
    # может занимать непропорционально много времени. Первоначальные места
    # посева при этом всегда остаются неизменными.
    max_swaps = min(24, max(8, len(placed) // 16))
    for _ in range(max_swaps):
        best_cost = cost
        best_swap: tuple[int, int] | None = None
        for positions in by_place.values():
            for index, left in enumerate(positions):
                first = placed[left]
                if first is None:
                    continue
                for right in positions[index + 1:]:
                    second = placed[right]
                    if second is None or first.group == second.group:
                        continue
                    delta = [0] * rounds
                    for other in by_group[first.group] - {left}:
                        delta[_round_of_possible_meeting(left, other) - 1] -= 1
                        delta[_round_of_possible_meeting(right, other) - 1] += 1
                    for other in by_group[second.group] - {right}:
                        delta[_round_of_possible_meeting(right, other) - 1] -= 1
                        delta[_round_of_possible_meeting(left, other) - 1] += 1
                    candidate = tuple(a + b for a, b in zip(cost, delta))
                    if candidate < best_cost:
                        best_cost, best_swap = candidate, (left, right)
        if best_swap is None:
            return placed
        left, right = best_swap
        first, second = placed[left], placed[right]
        assert first is not None and second is not None
        by_group[first.group].remove(left)
        by_group[first.group].add(right)
        by_group[second.group].remove(right)
        by_group[second.group].add(left)
        placed[left], placed[right] = second, first
        cost = best_cost
    return placed


def seed_group_playoff_slots(
    group_rankings: Mapping[str, Sequence[int | None]],
) -> list[int | None]:
    """Возвращает слоты первого раунда по местам в группах.

    В каждой группе список ID уже упорядочен от первого места к последнему.
    ``None`` сохраняет место исключённого участника без участия в сетке.
    Группы перебираются в стабильном порядке, победители получают высшие
    номера посева, участники низших мест — низшие. Перестановки внутри
    одного места допускаются только ради разнесения бывших соперников.
    """
    entrants = [
        _Qualifier(cp_id=cp_id, group=group, place=index + 1)
        for group, ids in sorted(group_rankings.items())
        for index, cp_id in enumerate(ids)
        if cp_id is not None
    ]
    entrants.sort(key=lambda entrant: (entrant.place, entrant.group, entrant.cp_id))
    if len({entrant.cp_id for entrant in entrants}) != len(entrants):
        raise ValueError("Один участник не может выйти в плей-офф из нескольких групп")
    if len(entrants) < 2:
        raise ValueError("Недостаточно участников для плей-офф")

    slots = next_power_of_two(len(entrants))
    placed = [entrants[seed - 1] if seed <= len(entrants) else None for seed in _seed_order(slots)]
    placed = _improve_group_spread(placed)
    return [entrant.cp_id if entrant else None for entrant in placed]
