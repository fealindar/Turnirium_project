"""Отложенные санкции поединка, фиксируемые до подтверждения его результата."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Match, MatchEvent
from .common import audit, json_load


def pending_penalties(match: Match) -> dict[str, str]:
    """Определяет санкции на обе стороны без преждевременного завершения боя."""
    active = [event for event in match.events if not event.undone]
    technical = {event.side for event in active if event.event_type == "technical_loss"}
    forfeits = {
        event.side for event in active
        if event.event_type == "warning"
        and json_load(event.payload_json, {}).get("action") == "forfeit"
    }
    result: dict[str, str] = {}
    for side, cp in (("red", match.red_cp), ("blue", match.blue_cp)):
        if side in technical:
            result[side] = "TECHNICAL_LOSS"
        elif cp and cp.disqualified:
            result[side] = "DISQUALIFICATION"
        elif side in forfeits:
            result[side] = "WARNING_FORFEIT"
    return result


def toggle_technical_loss(db: Session, match: Match, side: str) -> dict[str, str]:
    """Переключает отметку о поражении: это не окончательный результат боя."""
    if match.category.status == "completed" or match.status in {"finished", "staged", "blocked", "cancelled"}:
        raise ValueError("Поединок недоступен для отметок о техническом поражении")
    if match.red_cp_id is None or match.blue_cp_id is None or side not in {"red", "blue"}:
        raise ValueError("Выберите существующую сторону поединка")
    event = next((event for event in reversed(match.events) if
                  event.event_type == "technical_loss" and event.side == side and not event.undone), None)
    if event:
        event.undone = True
    else:
        db.add(MatchEvent(match_id=match.id, event_type="technical_loss", side=side))
    match.version += 1
    audit(db, match.category.tournament_id, "TECHNICAL_LOSS_MARK_CHANGED", "match", match.id,
          match.area_id, {"side": side, "marked": event is None})
    db.commit()
    db.expire(match, ["events"])
    return pending_penalties(match)
