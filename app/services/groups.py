"""Групповой этап, круговой формат и перестройка состава групп."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Category, CategoryParticipant, Match
from .common import _affiliation_penalty, _delete_match_rows, _layout_match_locked, _norm, audit, clear_category_matches
from .scheduling import auto_assign_ready_matches

def _balanced_groups(cps: list[CategoryParticipant], target_size: int) -> list[list[CategoryParticipant]]:
    n = len(cps)
    if n < 2:
        return [cps]
    target_size = max(2, target_size)
    group_count = max(1, round(n / target_size))
    while group_count > 1 and n // group_count < 2:
        group_count -= 1
    groups = [[] for _ in range(group_count)]
    base, extra = divmod(n, group_count)
    capacities = [base + (1 if i < extra else 0) for i in range(group_count)]
    club_freq: dict[str, int] = defaultdict(int)
    city_freq: dict[str, int] = defaultdict(int)
    for cp in cps:
        club_freq[_norm(cp.participant.club)] += 1
        city_freq[_norm(cp.participant.city)] += 1
    # Сначала размещаем сложные аффилиации, затем выбираем наименее конфликтную группу.
    ordered = sorted(cps, key=lambda cp: (-club_freq[_norm(cp.participant.club)], -city_freq[_norm(cp.participant.city)], cp.seed_order, cp.id))
    for cp in ordered:
        choices = []
        for idx, group in enumerate(groups):
            if len(group) >= capacities[idx]:
                continue
            conflict = sum(_affiliation_penalty(cp, other) for other in group)
            choices.append((conflict, len(group), idx))
        _, _, best = min(choices)
        groups[best].append(cp)
    return groups

def _spread_group_pair_order(
    pairs: list[tuple[CategoryParticipant, CategoryParticipant]],
) -> list[tuple[CategoryParticipant, CategoryParticipant]]:
    """Упорядочивает круговые пары, обеспечивая бойцам максимум возможного отдыха.

    Главная цель — не ставить одного участника в два соседних боя. При равных
    вариантах выбирается пара, чей наименее отдохнувший боец ждал дольше. Небольшой
    просмотр вперёд сохраняет варианты без пересечений. Для групп из 3–4 бойцов
    некоторые соседние повторы математически неизбежны.
    """
    if len(pairs) < 2:
        return list(pairs)

    remaining = list(pairs)
    original_pos = {
        frozenset((a.id, b.id)): idx for idx, (a, b) in enumerate(remaining)
    }
    ordered: list[tuple[CategoryParticipant, CategoryParticipant]] = []
    last_seen: dict[int, int] = {}

    while remaining:
        previous_ids = (
            {ordered[-1][0].id, ordered[-1][1].id} if ordered else set()
        )

        def key(pair: tuple[CategoryParticipant, CategoryParticipant]):
            a, b = pair
            ids = {a.id, b.id}
            immediate_repeat = 1 if ids & previous_ids else 0

            # Число полных чужих боёв с последнего выхода бойца.
            # Бойцы без предыдущего выхода получают заведомо большой запас отдыха.
            rest_values = []
            for cid in (a.id, b.id):
                if cid in last_seen:
                    rest_values.append(len(ordered) - 1 - last_seen[cid])
                else:
                    rest_values.append(len(ordered) + 1000)
            min_rest = min(rest_values)

            # При равенстве берём пару с меньшим числом непересекающихся продолжений,
            # сохраняя больше возможностей избежать соседних повторов дальше.
            future_disjoint = 0
            for other_a, other_b in remaining:
                if other_a.id == a.id and other_b.id == b.id:
                    continue
                if not ids & {other_a.id, other_b.id}:
                    future_disjoint += 1

            pair_key = frozenset((a.id, b.id))
            return (
                immediate_repeat,
                -min_rest,
                future_disjoint,
                original_pos[pair_key],
                min(a.id, b.id),
                max(a.id, b.id),
            )

        chosen = min(remaining, key=key)
        remaining.remove(chosen)
        ordered.append(chosen)
        pos = len(ordered) - 1
        last_seen[chosen[0].id] = pos
        last_seen[chosen[1].id] = pos

    return ordered

def _create_group_matches(
    db: Session,
    category: Category,
    groups: list[list[CategoryParticipant]],
    start_match_no: int = 1,
    *,
    initial_status: str = "staged",
    skip_pairs: set[frozenset[int]] | None = None,
) -> list[Match]:
    created: list[Match] = []
    match_no = start_match_no
    skip_pairs = skip_pairs or set()
    for idx, members in enumerate(groups):
        group_name = chr(ord("A") + idx)
        for cp in members:
            cp.group_name = group_name
        active_members = [cp for cp in members if cp.participant.active and cp.participant.status != "withdrawn" and not cp.disqualified]
        candidate_pairs = [
            (a, b)
            for a, b in combinations(active_members, 2)
            if frozenset((a.id, b.id)) not in skip_pairs
        ]
        ordered_pairs = _spread_group_pair_order(candidate_pairs)
        round_no = 1
        for a, b in ordered_pairs:
            m = Match(
                category_id=category.id,
                stage="group",
                round_no=round_no,
                match_no=match_no,
                group_name=group_name,
                red_cp_id=a.id,
                blue_cp_id=b.id,
                status=initial_status,
                duration_ms=category.match_duration_sec * 1000,
                remaining_ms=category.match_duration_sec * 1000,
            )
            db.add(m)
            created.append(m)
            match_no += 1
            round_no += 1
    return created

def generate_round_robin(db: Session, category: Category) -> list[Match]:
    """Создаёт самостоятельный формат «все со всеми» без плей-офф."""
    clear_category_matches(db, category)
    cps = db.scalars(select(CategoryParticipant).where(
        CategoryParticipant.category_id == category.id,
        CategoryParticipant.disqualified.is_(False),
    ).order_by(CategoryParticipant.seed_order, CategoryParticipant.id)).all()
    cps = [cp for cp in cps if cp.participant.active and cp.participant.status != "withdrawn"]
    if len(cps) < 2:
        raise ValueError("Для формата «все со всеми» нужно минимум 2 активных участника")
    for cp in cps:
        cp.group_name = ""
    # Круговой формат использует тот же алгоритм разведения выходов, что и группы.
    # Это важно сделать до назначения на площадку: порядок match_no уже должен
    # давать бойцам максимально возможный отдых между соседними поединками.
    ordered_pairs = _spread_group_pair_order(list(combinations(cps, 2)))
    created: list[Match] = []
    for match_no, (a, b) in enumerate(ordered_pairs, 1):
        m = Match(
            category_id=category.id, stage="round_robin", round_no=match_no, match_no=match_no,
            red_cp_id=a.id, blue_cp_id=b.id, status="ready",
            duration_ms=category.match_duration_sec * 1000, remaining_ms=category.match_duration_sec * 1000,
        )
        db.add(m)
        created.append(m)
    db.flush()
    category.status = "ready"
    category.bracket_locked = False
    auto_assign_ready_matches(db, category.tournament_id)
    audit(db, category.tournament_id, "ROUND_ROBIN_GENERATED", "category", category.id, payload={"participants": len(cps)})
    db.commit()
    return created

def generate_groups(db: Session, category: Category) -> list[Match]:
    clear_category_matches(db, category)
    cps = db.scalars(select(CategoryParticipant).where(
        CategoryParticipant.category_id == category.id,
        CategoryParticipant.disqualified.is_(False),
    ).order_by(CategoryParticipant.seed_order, CategoryParticipant.id)).all()
    cps = [cp for cp in cps if cp.participant.active and cp.participant.status != "withdrawn"]
    if len(cps) < 2:
        raise ValueError("Для групп нужно минимум 2 активных участника")
    groups = _balanced_groups(cps, category.group_target_size)
    created = _create_group_matches(db, category, groups)
    db.flush()
    category.status = "ready"
    category.bracket_locked = False
    auto_assign_ready_matches(db, category.tournament_id)
    audit(db, category.tournament_id, "GROUPS_GENERATED", "category", category.id, payload={"groups": len(groups)})
    db.commit()
    return created

def rebuild_groups_from_assignments(db: Session, category: Category, group_members: dict[str, list[int]]) -> list[Match]:
    if db.scalar(select(func.count(Match.id)).where(Match.category_id == category.id, Match.stage == "playoff")):
        raise ValueError("Состав групп нельзя менять после создания плей-офф")

    existing = db.scalars(select(Match).where(
        Match.category_id == category.id, Match.stage == "group"
    ).order_by(Match.match_no)).all()
    if not existing:
        raise ValueError("Сначала сформируйте группы")

    cps = {cp.id: cp for cp in db.scalars(select(CategoryParticipant).where(CategoryParticipant.category_id == category.id)).all()}
    used: set[int] = set()
    groups: list[list[CategoryParticipant]] = []
    requested_group: dict[int, str] = {}
    for group_name in sorted(group_members):
        members: list[CategoryParticipant] = []
        for cid in group_members[group_name]:
            if cid in cps and cid not in used:
                members.append(cps[cid])
                used.add(cid)
        if members:
            groups.append(members)
    for idx, members in enumerate(groups):
        canonical = chr(ord("A") + idx)
        for cp in members:
            requested_group[cp.id] = canonical

    missing = [cp for cp in cps.values() if cp.id not in used and not cp.disqualified]
    for cp in missing:
        if not groups:
            groups.append([])
        idx = min(range(len(groups)), key=lambda i: len(groups[i]))
        groups[idx].append(cp)
        requested_group[cp.id] = chr(ord("A") + idx)

    locked_cp_ids: set[int] = set()
    preserved_pairs: set[frozenset[int]] = set()
    for m in existing:
        if _layout_match_locked(m):
            if m.red_cp_id:
                locked_cp_ids.add(m.red_cp_id)
            if m.blue_cp_id:
                locked_cp_ids.add(m.blue_cp_id)
            if m.red_cp_id and m.blue_cp_id:
                preserved_pairs.add(frozenset((m.red_cp_id, m.blue_cp_id)))

    for cid in locked_cp_ids:
        cp = cps.get(cid)
        if cp and requested_group.get(cid, cp.group_name) != cp.group_name:
            raise ValueError(f"{cp.participant.display_name}: группу нельзя менять после начала первого боя")

    stage_started = any(m.status != "staged" for m in existing)
    removable = [m for m in existing if not _layout_match_locked(m)]
    if removable:
        _delete_match_rows(db, removable)

    max_no = db.scalar(select(func.max(Match.match_no)).where(Match.category_id == category.id)) or 0
    created = _create_group_matches(
        db, category, groups, start_match_no=max_no + 1 if max_no else 1,
        initial_status="ready" if stage_started else "staged", skip_pairs=preserved_pairs,
    )
    db.flush()
    if stage_started:
        auto_assign_ready_matches(db, category.tournament_id)
    audit(db, category.tournament_id, "GROUPS_REARRANGED", "category", category.id, payload={"after_start": stage_started})
    db.commit()
    return created

def start_group_stage(db: Session, category: Category) -> list[Match]:
    rows = db.scalars(select(Match).where(Match.category_id == category.id, Match.stage == "group").order_by(Match.match_no)).all()
    if not rows:
        raise ValueError("Сначала сформируйте группы")
    if any(m.status != "staged" for m in rows):
        raise ValueError("Групповой этап уже начат")
    for m in rows:
        m.status = "ready"
    category.bracket_locked = True
    db.flush()
    auto_assign_ready_matches(db, category.tournament_id)
    audit(db, category.tournament_id, "GROUP_STAGE_STARTED", "category", category.id)
    db.commit()
    return rows
