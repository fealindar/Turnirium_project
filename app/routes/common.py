"""Общие функции HTTP-слоя и сериализация простых сущностей."""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ..models import CategoryParticipant, Participant

ModelT = TypeVar("ModelT")


def _get_or_404(db: Session, model: type[ModelT], entity_id: int, label: str) -> ModelT:
    """Возвращает ORM-объект или завершает запрос ответом 404."""

    obj = db.get(model, entity_id)
    if not obj:
        raise HTTPException(404, f"{label} не найден")
    return obj


async def _broadcast(request: Request, event: dict[str, Any]) -> None:
    """Рассылает событие подключённым WebSocket-клиентам, если менеджер запущен."""

    manager = getattr(request.app.state, "ws_manager", None)
    if manager:
        await manager.broadcast(event)


def _participant_dict(participant: Participant) -> dict[str, Any]:
    """Сериализует участника для HTTP-ответов организатора."""

    return {
        "id": participant.id,
        "tournament_id": participant.tournament_id,
        "first_name": participant.first_name,
        "last_name": participant.last_name,
        "name": participant.display_name,
        "club": participant.club,
        "city": participant.city,
        "active": participant.active,
        "status": participant.status,
    }


def _cp_dict(link: CategoryParticipant) -> dict[str, Any]:
    """Сериализует участие бойца в конкретной категории."""

    return {
        "id": link.id,
        "participant_id": link.participant_id,
        "name": link.participant.display_name,
        "club": link.participant.club,
        "city": link.participant.city,
        "seed_order": link.seed_order,
        "warnings": link.cumulative_warnings,
        "disqualified": link.disqualified,
        "group": link.group_name,
        "participant_status": link.participant.status,
    }
