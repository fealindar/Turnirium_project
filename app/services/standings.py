"""Расчёт итоговых и промежуточных таблиц результатов."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Category, CategoryParticipant, Match

def _points_standings(
    db: Session,
    category_id: int,
    group_name: str | None = None,
    *,
    stage: str | None = None,
) -> list[dict[str, Any]]:
    """Строит таблицу форматов, где главным критерием служат турнирные очки."""
    category = db.get(Category, category_id)
    win_points = category.win_points if category else 3
    draw_points = category.draw_points if category else 1
    cps_stmt = select(CategoryParticipant).where(CategoryParticipant.category_id == category_id)
    if group_name is not None:
        cps_stmt = cps_stmt.where(CategoryParticipant.group_name == group_name)
    cps = db.scalars(cps_stmt).all()
    stats = {
        cp.id: {
            "cp": cp, "wins": 0, "draws": 0, "losses": 0,
            "for": 0, "against": 0, "played": 0, "points": 0,
        }
        for cp in cps
    }
    q = select(Match).where(Match.category_id == category_id, Match.status == "finished")
    if stage:
        q = q.where(Match.stage == stage)
    elif group_name is not None:
        q = q.where(Match.stage == "group", Match.group_name == group_name)
    for m in db.scalars(q).all():
        if group_name is not None and m.group_name != group_name:
            continue
        is_draw = m.result_reason == "DRAW" and m.red_cp_id is not None and m.blue_cp_id is not None
        for cp_id, scored, conceded in (
            (m.red_cp_id, m.red_score, m.blue_score),
            (m.blue_cp_id, m.blue_score, m.red_score),
        ):
            if cp_id not in stats:
                continue
            st = stats[cp_id]
            st["played"] += 1
            st["for"] += scored
            st["against"] += conceded
            if is_draw:
                st["draws"] += 1
                st["points"] += draw_points
            elif m.winner_cp_id == cp_id:
                st["wins"] += 1
                st["points"] += win_points
            elif m.winner_cp_id:
                st["losses"] += 1

    rows = []
    for stat in stats.values():
        cp = stat["cp"]
        numeric = {k: v for k, v in stat.items() if k != "cp"}
        rows.append({
            "ranking_type": "points",
            "cp_id": cp.id,
            "name": cp.participant.display_name,
            "club": cp.participant.club,
            "city": cp.participant.city,
            "group": cp.group_name,
            "participant_status": cp.participant.status,
            **numeric,
            "diff": numeric["for"] - numeric["against"],
            "warnings": cp.cumulative_warnings,
            "disqualified": cp.disqualified,
        })
    rows.sort(key=lambda r: (
        r["disqualified"] or r.get("participant_status") == "withdrawn",
        -r["points"], -r["wins"], -r["diff"], -r["for"], r["name"],
    ))
    for i, row in enumerate(rows, 1):
        row["place"] = i
    return rows

def _elimination_round_label(round_no: int, final_round: int) -> str:
    distance = final_round - round_no
    if distance <= 0:
        return "Финал"
    if distance == 1:
        return "Полуфинал"
    denominators = {2: 4, 3: 8, 4: 16, 5: 32, 6: 64, 7: 128}
    if distance in denominators:
        return f"1/{denominators[distance]} финала"
    return f"Раунд {round_no}"

def _elimination_reason_rank(reason: str) -> int:
    # Активный боец без поражения на выбывание остаётся выше участника,
    # уже выбывшего на той же отображаемой стадии.
    if not reason:
        return -1
    # Поражение по счёту ставится выше административного или штрафного поражения
    # при выбывании двух бойцов на одной стадии сетки.
    return {
        "POINTS": 0,
        "WARNING_FORFEIT": 1,
        "TECHNICAL_LOSS": 2,
        "WITHDRAWAL": 3,
        "DISQUALIFICATION": 4,
    }.get(reason, 1)

def _oriented_score(match: Match, cp_id: int) -> tuple[int, int]:
    if match.red_cp_id == cp_id:
        return match.red_score, match.blue_score
    if match.blue_cp_id == cp_id:
        return match.blue_score, match.red_score
    return 0, 0

def _elimination_performance(
    matches: list[Match],
    participant_ids: set[int],
) -> dict[int, dict[str, int]]:
    """Собирает счёт и победы участников на этапе с выбыванием."""
    perf = {
        cp_id: {"wins": 0, "losses": 0, "for": 0, "against": 0, "played": 0}
        for cp_id in participant_ids
    }
    for match in matches:
        if match.status != "finished" or match.result_reason == "BYE":
            continue
        for cp_id, scored, conceded in (
            (match.red_cp_id, match.red_score, match.blue_score),
            (match.blue_cp_id, match.blue_score, match.red_score),
        ):
            if cp_id not in perf:
                continue
            stat = perf[cp_id]
            stat["played"] += 1
            stat["for"] += scored
            stat["against"] += conceded
            if match.winner_cp_id == cp_id:
                stat["wins"] += 1
            elif match.winner_cp_id is not None:
                stat["losses"] += 1
    return perf


def _fixed_elimination_places(final: Match | None, bronze: Match | None) -> dict[int, int]:
    """Возвращает однозначные места, определённые финалом и бронзовым боем."""
    fixed: dict[int, int] = {}
    if final and final.status == "finished" and final.winner_cp_id:
        fixed[final.winner_cp_id] = 1
        runner = final.blue_cp_id if final.winner_cp_id == final.red_cp_id else final.red_cp_id
        if runner:
            fixed[runner] = 2
    if bronze and bronze.status == "finished" and bronze.winner_cp_id:
        fixed[bronze.winner_cp_id] = 3
        fourth = bronze.blue_cp_id if bronze.winner_cp_id == bronze.red_cp_id else bronze.red_cp_id
        if fourth:
            fixed[fourth] = 4
    return fixed


def _elimination_stage_label(
    cp_id: int,
    reached_round: int,
    final_round: int,
    fixed_place: int | None,
    bronze: Match | None,
) -> str:
    """Формирует человекочитаемую стадию, до которой дошёл участник."""
    if fixed_place == 1:
        return "Победитель"
    if fixed_place == 2:
        return "Финал"
    if fixed_place == 3:
        return "3-е место"
    if fixed_place == 4:
        return "Бой за 3-е место"
    if bronze and cp_id in (bronze.red_cp_id, bronze.blue_cp_id):
        return "Бой за 3-е место"
    return _elimination_round_label(reached_round, final_round)


def _elimination_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Сортирует сначала по достигнутой стадии, затем по результату внутри стадии."""
    fixed = row["_fixed_place"]
    fixed_order = fixed if fixed is not None else 999
    return (
        row["_progress_tier"],
        fixed_order,
        row["_reason_rank"],
        -row["_elim_diff"],
        -row["_elim_for"],
        -row["wins"],
        -row["diff"],
        -row["for"],
        row["warnings"],
        row["_seed"],
        row["name"],
    )


def _build_elimination_row(
    cp: CategoryParticipant,
    cp_matches: list[Match],
    perf: dict[str, int],
    *,
    stage: str,
    final_round: int,
    final: Match | None,
    bronze: Match | None,
    fixed_place: int | None,
) -> dict[str, Any]:
    """Строит одну строку итоговой таблицы этапа с выбыванием."""
    cp_id = cp.id
    reached_round = max(match.round_no for match in cp_matches)
    losses = [
        match
        for match in cp_matches
        if match.status == "finished" and match.winner_cp_id and match.winner_cp_id != cp_id
    ]
    elimination_match = max(losses, key=lambda match: (match.round_no, match.match_no)) if losses else None

    ranking_match = elimination_match
    if fixed_place in (1, 2):
        ranking_match = final
    elif fixed_place in (3, 4):
        ranking_match = bronze

    scored, conceded = _oriented_score(ranking_match, cp_id) if ranking_match else (0, 0)
    if final and cp_id in (final.red_cp_id, final.blue_cp_id):
        progress_tier = 0
    elif bronze and cp_id in (bronze.red_cp_id, bronze.blue_cp_id):
        progress_tier = 1
    else:
        progress_tier = max(0, final_round - reached_round)

    return {
        "ranking_type": "elimination",
        "cp_id": cp_id,
        "name": cp.participant.display_name,
        "club": cp.participant.club,
        "city": cp.participant.city,
        "group": cp.group_name,
        "participant_status": cp.participant.status,
        "stage": stage,
        "stage_round": reached_round,
        "stage_label": _elimination_stage_label(cp_id, reached_round, final_round, fixed_place, bronze),
        "played": perf["played"],
        "wins": perf["wins"],
        "draws": 0,
        "losses": perf["losses"],
        "points": 0,
        "for": perf["for"],
        "against": perf["against"],
        "diff": perf["for"] - perf["against"],
        "warnings": cp.cumulative_warnings,
        "disqualified": cp.disqualified,
        "last_score_for": scored,
        "last_score_against": conceded,
        "last_score": (
            f"{scored}:{conceded}"
            if ranking_match and ranking_match.status == "finished" and ranking_match.result_reason != "BYE"
            else ""
        ),
        "last_result": ranking_match.result_reason if ranking_match and ranking_match.status == "finished" else "",
        "_fixed_place": fixed_place,
        "_progress_tier": progress_tier,
        "_reason_rank": _elimination_reason_rank(elimination_match.result_reason if elimination_match else ""),
        "_elim_diff": (scored - conceded) if elimination_match else 0,
        "_elim_for": scored if elimination_match else 0,
        "_seed": cp.seed_order,
    }


def elimination_standings(db: Session, category_id: int, stage: str) -> list[dict[str, Any]]:
    """Ранжирует бойцов по достигнутой стадии, затем по результату внутри стадии."""
    matches = db.scalars(
        select(Match)
        .where(Match.category_id == category_id, Match.stage == stage)
        .order_by(Match.round_no, Match.match_no)
    ).all()
    regular = [match for match in matches if not match.is_third_place]
    if not regular:
        return []

    final_round = max(match.round_no for match in regular)
    final = next((match for match in regular if match.round_no == final_round), None)
    bronze = next((match for match in matches if match.is_third_place), None)
    participant_ids = {
        cp_id
        for match in matches
        for cp_id in (match.red_cp_id, match.blue_cp_id)
        if cp_id is not None
    }
    if not participant_ids:
        return []

    participants = {
        cp.id: cp
        for cp in db.scalars(
            select(CategoryParticipant).where(
                CategoryParticipant.category_id == category_id,
                CategoryParticipant.id.in_(participant_ids),
            )
        ).all()
    }
    performance = _elimination_performance(matches, set(participants))
    fixed_places = _fixed_elimination_places(final, bronze)

    rows: list[dict[str, Any]] = []
    for cp_id, cp in participants.items():
        cp_matches = [match for match in regular if cp_id in (match.red_cp_id, match.blue_cp_id)]
        if not cp_matches:
            continue
        rows.append(
            _build_elimination_row(
                cp,
                cp_matches,
                performance[cp_id],
                stage=stage,
                final_round=final_round,
                final=final,
                bronze=bronze,
                fixed_place=fixed_places.get(cp_id),
            )
        )

    rows.sort(key=_elimination_sort_key)
    private_fields = ("_fixed_place", "_progress_tier", "_reason_rank", "_elim_diff", "_elim_for", "_seed")
    for place, row in enumerate(rows, 1):
        row["place"] = place
        for field in private_fields:
            row.pop(field, None)
    return rows

def standings(
    db: Session,
    category_id: int,
    group_name: str | None = None,
    swiss_only: bool = False,
    round_robin_only: bool = False,
) -> list[dict[str, Any]]:
    category = db.get(Category, category_id)
    if not category:
        return []
    if group_name is not None:
        return _points_standings(db, category_id, group_name, stage="group")
    if swiss_only or category.format == "swiss":
        return _points_standings(db, category_id, stage="swiss")
    if round_robin_only or category.format == "round_robin":
        return _points_standings(db, category_id, stage="round_robin")
    if category.format == "knockout":
        return elimination_standings(db, category_id, "knockout")
    if category.format == "groups":
        has_playoff = db.scalar(select(func.count(Match.id)).where(
            Match.category_id == category_id, Match.stage == "playoff"
        ))
        group_rows = _points_standings(db, category_id, stage="group")
        if not has_playoff:
            return group_rows
        playoff_rows = elimination_standings(db, category_id, "playoff")
        playoff_ids = {r["cp_id"] for r in playoff_rows}
        non_qualifiers = [r for r in group_rows if r["cp_id"] not in playoff_ids]
        for row in non_qualifiers:
            row["ranking_type"] = "elimination"
            row["stage"] = "group"
            row["stage_round"] = 0
            row["stage_label"] = "Групповой этап"
            row["last_score"] = ""
            row["last_result"] = ""
        combined = playoff_rows + non_qualifiers
        for place, row in enumerate(combined, 1):
            row["place"] = place
        return combined
    return _points_standings(db, category_id)
