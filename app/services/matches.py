"""Проведение, завершение и корректировка результатов поединков."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, CategoryParticipant, Match, MatchEvent, Participant
from .brackets import _maybe_activate_or_bye, _propagate_loser_to_third_place, _third_place_match, propagate_winner
from .common import _delete_match_rows, _real_match_started, audit, effective_remaining_ms, json_load, match_dict, now_utc
from .scheduling import auto_assign_ready_matches

VALID_RESULT_REASONS = {
    "POINTS",
    "DRAW",
    "TECHNICAL_LOSS",
    "WARNING_FORFEIT",
    "DISQUALIFICATION",
    "WITHDRAWAL",
}


def _validate_result_reason(match: Match, reason: str) -> bool:
    """Проверяет причину результата и возвращает признак ничьей."""
    if reason not in VALID_RESULT_REASONS:
        raise ValueError("Неизвестная причина завершения поединка")
    if reason == "DRAW" and match.stage not in ("group", "swiss", "round_robin"):
        raise ValueError("Ничья разрешена только в группах, швейцарской системе и формате «все со всеми»")
    return reason == "DRAW"


def _finish_match(
    db: Session,
    match: Match,
    winner_cp_id: int | None,
    reason: str,
    *,
    commit: bool,
) -> Match:
    """Завершает бой внутри текущей транзакции."""
    if match.status == "staged":
        raise ValueError("Этап еще не начат")
    if match.status == "finished":
        raise ValueError("Поединок уже завершен")
    is_draw = _validate_result_reason(match, reason)
    if match.red_cp_id is None or match.blue_cp_id is None:
        raise ValueError("Нельзя вручную завершить бой без двух участников")
    if is_draw:
        if match.red_cp_id is None or match.blue_cp_id is None:
            raise ValueError("Ничья невозможна в поединке с BYE")
        winner_cp_id = None
    elif winner_cp_id is None or winner_cp_id not in (match.red_cp_id, match.blue_cp_id):
        raise ValueError("Победитель не является участником этого поединка")
    match.remaining_ms = effective_remaining_ms(match)
    match.timer_running = False
    match.timer_started_at = None
    match.timer_revision += 1
    match.winner_cp_id = winner_cp_id
    match.status = "finished"
    match.result_reason = reason
    match.finished_at = now_utc()
    match.version += 1
    match.category.bracket_locked = True
    db.add(MatchEvent(match_id=match.id, event_type="finish", value=winner_cp_id or 0, payload_json=json.dumps({"reason": reason})))
    audit(db, match.category.tournament_id, "MATCH_FINISHED", "match", match.id, match.area_id, {"winner_cp_id": winner_cp_id, "reason": reason})
    db.flush()
    if match.stage in ("knockout", "playoff"):
        propagate_winner(db, match)
        _propagate_loser_to_third_place(db, match)
    auto_assign_ready_matches(db, match.category.tournament_id)
    # Текущий бой остаётся на площадке до выбора следующего, чтобы табло показывало победителя.
    if commit:
        db.commit()
    else:
        db.flush()
    return match


def finish_match(
    db: Session,
    match: Match,
    winner_cp_id: int | None,
    reason: str = "POINTS",
) -> Match:
    """Завершает бой и фиксирует транзакцию для внешнего вызывающего кода."""
    return _finish_match(db, match, winner_cp_id, reason, commit=True)


def _dependent_bracket_matches(db: Session, match: Match) -> list[Match]:
    """Возвращает бои, состав которых может измениться после коррекции результата сетки."""
    out: list[Match] = []
    seen: set[int] = set()
    stack: list[int] = [match.next_match_id] if match.next_match_id else []
    while stack:
        mid = stack.pop()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        row = db.get(Match, mid)
        if not row:
            continue
        out.append(row)
        if row.next_match_id:
            stack.append(row.next_match_id)
        bronze = _third_place_match(db, row.category_id, row.stage)
        if bronze and row.id in (bronze.source_red_match_id, bronze.source_blue_match_id) and bronze.id not in seen:
            stack.append(bronze.id)
    bronze = _third_place_match(db, match.category_id, match.stage)
    if bronze and match.id in (bronze.source_red_match_id, bronze.source_blue_match_id) and bronze.id not in seen:
        out.append(bronze)
    return out

def _clear_match_runtime(match: Match, *, keep_participants: bool) -> None:
    if not keep_participants:
        match.red_cp_id = None
        match.blue_cp_id = None
    match.red_score = 0
    match.blue_score = 0
    match.red_warnings = 0
    match.blue_warnings = 0
    match.winner_cp_id = None
    match.result_reason = ""
    match.status = "pending" if keep_participants else "blocked"
    match.remaining_ms = match.duration_ms
    match.timer_running = False
    match.timer_started_at = None
    match.timer_revision += 1
    match.finished_at = None
    match.started_at = None
    match.version += 1

def _recompute_bracket_stage(db: Session, category: Category, stage: str) -> None:
    """Пересчитывает производные слоты и BYE, сохраняя уже проведённые реальные бои."""
    rows = db.scalars(select(Match).where(Match.category_id == category.id, Match.stage == stage).order_by(Match.round_no, Match.match_no)).all()
    if not rows:
        return
    regular = [m for m in rows if not m.is_third_place]
    bronze = next((m for m in rows if m.is_third_place), None)
    real_ids = {m.id for m in rows if _real_match_started(m)}

    for m in rows:
        if m.id in real_ids:
            continue
        if m.round_no == 1 and not m.is_third_place:
            if m.status == "finished" and m.result_reason == "BYE":
                _clear_match_runtime(m, keep_participants=True)
        else:
            _clear_match_runtime(m, keep_participants=False)
    db.flush()

    rounds = sorted({m.round_no for m in regular})
    for rnd in rounds:
        current = [m for m in regular if m.round_no == rnd]
        # К этому моменту все исходные слоты предыдущего раунда уже заполнены.
        for m in current:
            if m.id not in real_ids:
                _maybe_activate_or_bye(db, m)
        db.flush()
        # Следующий раунд заполняем только после разрешения всех боёв текущего раунда,
        # иначе завершённый источник можно ошибочно принять за BYE.
        for m in current:
            if m.status != "finished" or not m.winner_cp_id:
                continue
            if m.next_match_id:
                nxt = db.get(Match, m.next_match_id)
                if nxt:
                    if m.next_slot == "red":
                        nxt.red_cp_id = m.winner_cp_id
                    else:
                        nxt.blue_cp_id = m.winner_cp_id
            if bronze and m.id in (bronze.source_red_match_id, bronze.source_blue_match_id):
                loser_id = None
                if m.red_cp_id and m.blue_cp_id:
                    loser_id = m.blue_cp_id if m.winner_cp_id == m.red_cp_id else m.red_cp_id
                if m.id == bronze.source_red_match_id:
                    bronze.red_cp_id = loser_id
                else:
                    bronze.blue_cp_id = loser_id
        db.flush()

    if bronze and bronze.id not in real_ids:
        _maybe_activate_or_bye(db, bronze)
    db.flush()

def _adjust_corrected_warnings(db: Session, match: Match, red_warnings: int, blue_warnings: int) -> list[CategoryParticipant]:
    changed: list[CategoryParticipant] = []
    limit = match.category.cumulative_warning_limit
    for cp, old_count, new_count in (
        (match.red_cp, match.red_warnings, red_warnings),
        (match.blue_cp, match.blue_warnings, blue_warnings),
    ):
        if not cp:
            continue
        delta = new_count - old_count
        if not delta:
            continue
        new_total = max(0, cp.cumulative_warnings + delta)
        old_dsq = bool(cp.disqualified)
        new_dsq = bool(limit > 0 and new_total >= limit)
        if old_dsq and not new_dsq:
            dsq_results = db.scalars(select(Match).where(
                Match.category_id == match.category_id,
                Match.id != match.id,
                Match.status == "finished",
                Match.result_reason == "DISQUALIFICATION",
                ((Match.red_cp_id == cp.id) | (Match.blue_cp_id == cp.id)),
            )).all()
            if dsq_results:
                raise ValueError("Нельзя уменьшить предупреждения ниже лимита DSQ: после этой дисквалификации уже есть технические результаты. Сначала исправьте их.")
        if not old_dsq and new_dsq:
            later_real = db.scalars(select(Match).where(
                Match.category_id == match.category_id,
                Match.id != match.id,
                ((Match.red_cp_id == cp.id) | (Match.blue_cp_id == cp.id)),
            )).all()
            if any(_real_match_started(m) for m in later_real):
                raise ValueError("Исправление приводит к дисквалификации, но у участника уже есть другие начатые/завершенные бои. Сначала исправьте более поздние результаты.")
        cp.cumulative_warnings = new_total
        cp.disqualified = new_dsq
        changed.append(cp)
    return changed

def correct_finished_match(
    db: Session,
    match: Match,
    *,
    red_score: int,
    blue_score: int,
    red_warnings: int,
    blue_warnings: int,
    winner_cp_id: int | None,
    reason: str,
) -> dict[str, Any]:
    """Исправляет завершённый бой и сохраняет согласованность состояния турнира."""
    if match.status != "finished":
        raise ValueError("Корректировка доступна только для завершенного поединка")
    if match.category.status == "completed":
        raise ValueError("Категория завершена. Сначала верните ее в активные")
    if red_warnings < 0 or blue_warnings < 0:
        raise ValueError("Количество предупреждений не может быть отрицательным")
    is_draw = _validate_result_reason(match, reason)
    if match.red_cp_id is None or match.blue_cp_id is None:
        raise ValueError("Нельзя корректировать результат боя без двух участников")
    if is_draw:
        if not match.red_cp_id or not match.blue_cp_id:
            raise ValueError("Ничья невозможна в поединке с BYE")
        winner_cp_id = None
    elif winner_cp_id is None or winner_cp_id not in (match.red_cp_id, match.blue_cp_id):
        raise ValueError("Победитель не является участником этого поединка")

    old = {
        "red_score": match.red_score,
        "blue_score": match.blue_score,
        "red_warnings": match.red_warnings,
        "blue_warnings": match.blue_warnings,
        "winner_cp_id": match.winner_cp_id,
        "reason": match.result_reason,
    }
    winner_changed = winner_cp_id != match.winner_cp_id
    notes: list[str] = []

    if match.stage in ("knockout", "playoff") and winner_changed:
        blocked = [m for m in _dependent_bracket_matches(db, match) if _real_match_started(m)]
        if blocked:
            raise ValueError("Нельзя изменить победителя: зависимый поединок уже начат или завершен. Сначала исправьте последующие бои в обратном порядке")

    if match.stage == "group":
        playoffs = db.scalars(select(Match).where(Match.category_id == match.category_id, Match.stage == "playoff")).all()
        if playoffs:
            if any(_real_match_started(m) for m in playoffs):
                raise ValueError("Нельзя исправить групповой бой после начала плей-офф: это может изменить состав вышедших участников")
            _delete_match_rows(db, playoffs)
            notes.append("Плей-офф удален, так как исправление могло изменить итоговую таблицу. Сформируйте его заново.")

    if match.stage == "swiss":
        later = db.scalars(select(Match).where(
            Match.category_id == match.category_id,
            Match.stage == "swiss",
            Match.round_no > match.round_no,
        ).order_by(Match.round_no, Match.match_no)).all()
        if later:
            if any(_real_match_started(m) for m in later):
                notes.append("Более поздние Swiss-туры уже проводились и сохранены; итоговая таблица пересчитана по исправленному результату.")
            else:
                _delete_match_rows(db, later)
                notes.append("Еще не проведенные последующие Swiss-туры удалены. Сформируйте следующий тур заново.")

    changed_dsq = _adjust_corrected_warnings(db, match, red_warnings, blue_warnings)

    match.red_score = int(red_score)
    match.blue_score = int(blue_score)
    match.red_warnings = int(red_warnings)
    match.blue_warnings = int(blue_warnings)
    match.winner_cp_id = winner_cp_id
    match.result_reason = reason
    match.timer_running = False
    match.timer_started_at = None
    match.timer_revision += 1
    match.finished_at = now_utc()
    match.version += 1
    db.add(MatchEvent(
        match_id=match.id,
        event_type="correction",
        value=winner_cp_id or 0,
        payload_json=json.dumps({"before": old, "after": {
            "red_score": red_score, "blue_score": blue_score,
            "red_warnings": red_warnings, "blue_warnings": blue_warnings,
            "winner_cp_id": winner_cp_id, "reason": reason,
        }}, ensure_ascii=False),
    ))
    audit(db, match.category.tournament_id, "MATCH_CORRECTED", "match", match.id, match.area_id, {
        "before": old,
        "after": {"red_score": red_score, "blue_score": blue_score, "red_warnings": red_warnings,
                  "blue_warnings": blue_warnings, "winner_cp_id": winner_cp_id, "reason": reason},
    })
    db.flush()

    if match.stage in ("knockout", "playoff") and winner_changed:
        _recompute_bracket_stage(db, match.category, match.stage)

    auto_assign_ready_matches(db, match.category.tournament_id)
    db.flush()

    # Если исправленные предупреждения превышают лимит дисквалификации, закрываем будущие бои.
    for cp in changed_dsq:
        if not cp.disqualified:
            continue
        future = db.scalars(select(Match).where(
            Match.category_id == match.category_id,
            Match.id != match.id,
            Match.status.in_(["ready", "pending", "blocked"]),
            ((Match.red_cp_id == cp.id) | (Match.blue_cp_id == cp.id)),
        )).all()
        for fm in future:
            opponent = fm.blue_cp_id if fm.red_cp_id == cp.id else fm.red_cp_id
            if opponent:
                _finish_match(db, fm, opponent, "DISQUALIFICATION", commit=False)

    db.commit()
    return {"match": match_dict(match), "notes": notes}

def apply_score(db: Session, match: Match, side: str, delta: int) -> Match:
    if match.status == "staged":
        raise ValueError("Этап еще не начат")
    if match.status == "finished":
        raise ValueError("Поединок уже завершен")
    if match.status == "blocked" or match.red_cp_id is None or match.blue_cp_id is None:
        raise ValueError("Поединок ещё не готов к изменению счёта")
    if side not in ("red", "blue"):
        raise ValueError("Некорректная сторона")
    configured_deltas = {
        int(item.get("delta", 0))
        for item in json_load(match.category.score_buttons_json, [])
        if isinstance(item, dict)
    }
    if delta not in configured_deltas:
        raise ValueError("Такое изменение счёта не предусмотрено правилами категории")
    if side == "red":
        match.red_score += delta
    else:
        match.blue_score += delta
    match.version += 1
    db.add(MatchEvent(match_id=match.id, event_type="score", side=side, value=delta))
    audit(db, match.category.tournament_id, "SCORE_CHANGED", "match", match.id, match.area_id, {"side": side, "delta": delta})
    db.commit()
    return match

def add_warning(db: Session, match: Match, side: str) -> dict[str, Any]:
    if match.status == "staged":
        raise ValueError("Этап еще не начат")
    if match.status == "finished":
        raise ValueError("Поединок уже завершен")
    if match.status == "blocked" or match.red_cp_id is None or match.blue_cp_id is None:
        raise ValueError("Поединок ещё не готов к предупреждениям")
    cp = match.red_cp if side == "red" else match.blue_cp if side == "blue" else None
    if not cp:
        raise ValueError("Некорректная сторона")
    if side == "red":
        match.red_warnings += 1
        number = match.red_warnings
    else:
        match.blue_warnings += 1
        number = match.blue_warnings
    cp.cumulative_warnings += 1
    rules = json_load(match.category.warning_rules_json, [])
    rule = next((r for r in rules if int(r.get("number", -1)) == number), {"action": "warning", "delta": 0})
    action = rule.get("action", "warning")
    delta = int(rule.get("delta", 0) or 0)
    if action == "score_penalty" and delta:
        if side == "red":
            match.red_score += delta
        else:
            match.blue_score += delta
    outcome = {"warning_number": number, "action": action, "delta": delta, "cumulative": cp.cumulative_warnings, "disqualified": False}
    db.add(MatchEvent(match_id=match.id, event_type="warning", side=side, value=number, payload_json=json.dumps(rule, ensure_ascii=False)))
    match.version += 1

    if action == "forfeit":
        opponent = match.blue_cp_id if side == "red" else match.red_cp_id
        if opponent:
            _finish_match(db, match, opponent, "WARNING_FORFEIT", commit=False)
            outcome["match_forfeit"] = True
    limit = match.category.cumulative_warning_limit
    if limit > 0 and cp.cumulative_warnings >= limit:
        cp.disqualified = True
        outcome["disqualified"] = True
        if match.status != "finished":
            opponent = match.blue_cp_id if side == "red" else match.red_cp_id
            if opponent:
                _finish_match(db, match, opponent, "DISQUALIFICATION", commit=False)
        # Автоматически завершаем будущие готовые бои, где уже стоит этот участник.
        future = db.scalars(select(Match).where(
            Match.category_id == match.category_id,
            Match.status.in_(["ready", "pending", "blocked"]),
            Match.id != match.id,
        )).all()
        for fm in future:
            if fm.red_cp_id == cp.id and fm.blue_cp_id:
                _finish_match(db, fm, fm.blue_cp_id, "DISQUALIFICATION", commit=False)
            elif fm.blue_cp_id == cp.id and fm.red_cp_id:
                _finish_match(db, fm, fm.red_cp_id, "DISQUALIFICATION", commit=False)
    audit(db, match.category.tournament_id, "WARNING_ADDED", "match", match.id, match.area_id, {"side": side, **outcome})
    db.commit()
    return outcome

def undo_last_event(db: Session, match: Match) -> bool:
    event = db.scalar(select(MatchEvent).where(MatchEvent.match_id == match.id, MatchEvent.undone.is_(False), MatchEvent.event_type.in_(["score", "warning"]))
                      .order_by(MatchEvent.id.desc()))
    if not event or match.status == "finished":
        return False
    if event.event_type == "score":
        if event.side == "red":
            match.red_score -= event.value
        else:
            match.blue_score -= event.value
    elif event.event_type == "warning":
        cp = match.red_cp if event.side == "red" else match.blue_cp
        if event.side == "red":
            match.red_warnings = max(0, match.red_warnings - 1)
        else:
            match.blue_warnings = max(0, match.blue_warnings - 1)
        if cp:
            cp.cumulative_warnings = max(0, cp.cumulative_warnings - 1)
            # Откатываем штраф по счёту, если его породило отменяемое предупреждение.
            rule = json_load(event.payload_json, {})
            if rule.get("action") == "score_penalty":
                delta = int(rule.get("delta", 0) or 0)
                if event.side == "red":
                    match.red_score -= delta
                else:
                    match.blue_score -= delta
    event.undone = True
    match.version += 1
    audit(db, match.category.tournament_id, "UNDO", "match", match.id, match.area_id, {"event_id": event.id})
    db.commit()
    return True

def _participant_has_active_match(db: Session, participant_id: int) -> bool:
    """Проверяет, находится ли участник сейчас в реально начатом поединке."""

    count = db.scalar(
        select(Match.id)
        .join(
            CategoryParticipant,
            (Match.red_cp_id == CategoryParticipant.id)
            | (Match.blue_cp_id == CategoryParticipant.id),
        )
        .where(
            CategoryParticipant.participant_id == participant_id,
            Match.status == "in_progress",
        )
        .limit(1)
    )
    return count is not None


def withdraw_participant(
    db: Session,
    participant: Participant,
    *,
    commit: bool = True,
) -> None:
    """Помечает участника выбывшим и закрывает уже сформированные будущие бои."""

    if _participant_has_active_match(db, participant.id):
        raise ValueError(
            "Участник сейчас находится в активном поединке. Сначала завершите его."
        )

    participant.status = "withdrawn"
    participant.active = False
    links = db.scalars(
        select(CategoryParticipant).where(
            CategoryParticipant.participant_id == participant.id
        )
    ).all()
    for link in links:
        future = db.scalars(
            select(Match).where(
                Match.category_id == link.category_id,
                Match.status.in_(["blocked", "pending", "ready"]),
                (Match.red_cp_id == link.id) | (Match.blue_cp_id == link.id),
            )
        ).all()
        for match in future:
            opponent = (
                match.blue_cp_id if match.red_cp_id == link.id else match.red_cp_id
            )
            if opponent:
                _finish_match(db, match, opponent, "WITHDRAWAL", commit=False)

    audit(
        db,
        participant.tournament_id,
        "PARTICIPANT_WITHDRAWN",
        "participant",
        participant.id,
    )
    if commit:
        db.commit()
    else:
        db.flush()


def restore_participant(
    db: Session,
    participant: Participant,
    *,
    commit: bool = True,
) -> None:
    """Возвращает участника в активный список без изменения уже записанных результатов."""

    participant.status = "active"
    participant.active = True
    audit(
        db,
        participant.tournament_id,
        "PARTICIPANT_RESTORED",
        "participant",
        participant.id,
    )
    if commit:
        db.commit()
    else:
        db.flush()
