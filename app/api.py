"""Корневой маршрутизатор HTTP API.

Маршруты разнесены по предметным модулям в :mod:`app.routes`. Этот файл
сохраняет прежний публичный импорт ``from app.api import router`` и не
содержит бизнес-логики.
"""

from fastapi import APIRouter

from .routes import (
    categories,
    category_stages,
    exports,
    maintenance,
    matches,
    participants,
    public,
    schedule,
    system,
    templates,
    tournaments,
)


router = APIRouter(prefix="/api")

_SUBROUTERS = (
    system.router,
    tournaments.router,
    participants.router,
    categories.router,
    category_stages.router,
    schedule.router,
    matches.router,
    exports.router,
    templates.router,
    public.router,
    maintenance.router,
)

for subrouter in _SUBROUTERS:
    router.include_router(subrouter)
