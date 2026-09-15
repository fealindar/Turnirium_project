"""Публичные данные табло, расписания и результатов."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..engine import category_dict, match_dict, standings
from ..models import Area, Category, CategoryParticipant, Match, Tournament
from .common import _get_or_404

router = APIRouter()


def _public_area_rows(db: Session, tournament_id: int) -> list[dict]:
    """Собирает текущий и следующий бой каждой включённой площадки."""

    areas = db.scalars(
        select(Area)
        .where(Area.tournament_id == tournament_id, Area.enabled.is_(True))
        .order_by(Area.id)
    ).all()

    rows: list[dict] = []
    for area in areas:
        current = db.get(Match, area.current_match_id) if area.current_match_id else None
        if current and current.category.status == "completed":
            current = None

        next_match = db.scalar(
            select(Match)
            .join(Category)
            .where(
                Match.area_id == area.id,
                Category.status != "completed",
                Match.status.in_(["ready", "pending"]),
                Match.id != area.current_match_id,
            )
            .order_by(Match.queue_order, Match.id)
        )
        rows.append(
            {
                "area": {"id": area.id, "name": area.name},
                "current": match_dict(current) if current else None,
                "next": match_dict(next_match) if next_match else None,
            }
        )
    return rows


def _public_category_row(db: Session, category: Category) -> dict:
    """Собирает сетку и таблицы одной категории для общего экрана."""

    matches = db.scalars(
        select(Match)
        .where(Match.category_id == category.id)
        .order_by(Match.stage, Match.round_no, Match.match_no)
    ).all()

    group_tables: dict[str, list[dict]] = {}
    if category.format == "groups":
        group_names = [
            name
            for name in db.scalars(
                select(CategoryParticipant.group_name)
                .where(CategoryParticipant.category_id == category.id)
                .distinct()
            ).all()
            if name
        ]
        group_tables = {
            group_name: standings(db, category.id, group_name)
            for group_name in sorted(group_names)
        }

    overall: list[dict] = []
    if category.format in {"swiss", "round_robin"}:
        overall = standings(
            db,
            category.id,
            swiss_only=category.format == "swiss",
            round_robin_only=category.format == "round_robin",
        )

    return {
        "category": category_dict(category),
        "matches": [match_dict(match) for match in matches],
        "group_tables": group_tables,
        "standings": overall,
    }


@router.get("/tournaments/{tournament_id}/public-dashboard")
def public_dashboard(tournament_id: int, db: Session = Depends(get_db)):
    """Возвращает агрегированное состояние турнира для публичного экрана."""

    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    categories = db.scalars(
        select(Category)
        .where(Category.tournament_id == tournament_id)
        .order_by(Category.status == "completed", Category.id)
    ).all()

    return {
        "tournament": {
            "id": tournament.id,
            "name": tournament.name,
            "status": tournament.status,
        },
        "areas": _public_area_rows(db, tournament_id),
        "categories": [_public_category_row(db, category) for category in categories],
    }
