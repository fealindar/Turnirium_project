"""Операции HTTP с турнирами и площадками."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..engine import audit
from ..exporter import write_json_export, write_pdf_export
from ..models import Area, Category, Match, Tournament
from .common import _broadcast, _get_or_404
from .schemas import AreaIn, TournamentIn

router = APIRouter()


def _tournament_dict(tournament: Tournament) -> dict:
    """Сериализует основные настройки турнира для интерфейса организатора."""

    return {
        "id": tournament.id,
        "name": tournament.name,
        "venue": tournament.venue,
        "event_date": tournament.event_date,
        "status": tournament.status,
        "completed_at": (
            tournament.completed_at.isoformat() if tournament.completed_at else None
        ),
        "avoid_consecutive_matches": tournament.avoid_consecutive_matches,
        "preferred_match_gap": tournament.preferred_match_gap,
    }


@router.get("/tournaments")
def list_tournaments(db: Session = Depends(get_db)):
    rows = db.scalars(select(Tournament).order_by(Tournament.id.desc())).all()
    return [_tournament_dict(tournament) for tournament in rows]


@router.post("/tournaments")
async def create_tournament(
    data: TournamentIn,
    request: Request,
    db: Session = Depends(get_db),
):
    tournament = Tournament(
        name=data.name,
        venue=data.venue.strip(),
        event_date=data.event_date.strip(),
    )
    db.add(tournament)
    db.flush()

    # Площадка по умолчанию сокращает количество действий при первом запуске.
    db.add(Area(tournament_id=tournament.id, name="Площадка 1"))
    audit(
        db,
        tournament.id,
        "TOURNAMENT_CREATED",
        "tournament",
        tournament.id,
    )
    db.commit()
    await _broadcast(
        request,
        {"type": "tournament_changed", "tournament_id": tournament.id},
    )
    return {"id": tournament.id}


@router.get("/tournaments/{tournament_id}")
def get_tournament(tournament_id: int, db: Session = Depends(get_db)):
    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    return _tournament_dict(tournament)


@router.post("/tournaments/{tournament_id}/complete")
async def complete_tournament(
    tournament_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    active = db.scalar(
        select(func.count(Match.id))
        .join(Category)
        .where(
            Category.tournament_id == tournament.id,
            Match.status == "in_progress",
        )
    )
    if active:
        raise HTTPException(
            409,
            "Есть незавершенные активные поединки. Сначала завершите их.",
        )

    completed_at = datetime.now(timezone.utc)
    tournament.status = "completed"
    tournament.completed_at = completed_at
    for category in tournament.categories:
        if category.status != "completed":
            category.status = "completed"
            category.completed_at = completed_at
    for area in tournament.areas:
        area.current_match_id = None

    audit(
        db,
        tournament.id,
        "TOURNAMENT_COMPLETED",
        "tournament",
        tournament.id,
    )
    db.commit()

    export_error = None
    try:
        write_pdf_export(db, tournament)
        write_json_export(db, tournament)
    except Exception as exc:
        # Экспорт является производным артефактом и не должен откатывать завершение турнира.
        export_error = str(exc)

    await _broadcast(
        request,
        {"type": "tournament_changed", "tournament_id": tournament.id},
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": tournament.id},
    )
    return {
        "ok": True,
        "exports": {
            "pdf": f"/api/tournaments/{tournament.id}/export.pdf",
            "json": f"/api/tournaments/{tournament.id}/export.json",
        },
        "export_error": export_error,
    }


@router.post("/tournaments/{tournament_id}/reopen")
async def reopen_tournament(
    tournament_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    tournament.status = "active"
    tournament.completed_at = None
    db.commit()
    await _broadcast(
        request,
        {"type": "tournament_changed", "tournament_id": tournament.id},
    )
    return {"ok": True}


@router.get("/tournaments/{tournament_id}/areas")
def list_areas(tournament_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, Tournament, tournament_id, "Турнир")
    rows = db.scalars(
        select(Area).where(Area.tournament_id == tournament_id).order_by(Area.id)
    ).all()
    return [
        {
            "id": area.id,
            "name": area.name,
            "enabled": area.enabled,
            "current_match_id": area.current_match_id,
        }
        for area in rows
    ]


@router.post("/tournaments/{tournament_id}/areas")
async def create_area(
    tournament_id: int,
    data: AreaIn,
    request: Request,
    db: Session = Depends(get_db),
):
    _get_or_404(db, Tournament, tournament_id, "Турнир")
    area = Area(tournament_id=tournament_id, name=data.name.strip())
    db.add(area)
    db.commit()
    await _broadcast(
        request,
        {"type": "areas_changed", "tournament_id": tournament_id},
    )
    return {"id": area.id}


@router.delete("/areas/{area_id}")
async def delete_area(
    area_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Удаляет площадку и возвращает её незавершённые бои в неназначенные."""

    area = _get_or_404(db, Area, area_id, "Площадка")
    active_matches = db.scalar(
        select(func.count(Match.id)).where(
            Match.area_id == area.id,
            Match.status == "in_progress",
        )
    ) or 0
    if active_matches:
        raise HTTPException(
            409,
            "Нельзя удалить площадку, пока на ней идёт бой. Сначала завершите бой.",
        )

    assigned_matches = db.scalars(
        select(Match).where(Match.area_id == area.id)
    ).all()
    returned_to_pool = 0
    for match in assigned_matches:
        match.area_id = None
        if match.status != "finished":
            match.queue_order = 0
            returned_to_pool += 1

    tournament_id = area.tournament_id
    area.current_match_id = None
    audit(
        db,
        tournament_id,
        "AREA_DELETED",
        "area",
        area.id,
        payload={"name": area.name, "returned_to_pool": returned_to_pool},
    )
    db.delete(area)
    db.commit()

    await _broadcast(
        request,
        {"type": "areas_changed", "tournament_id": tournament_id, "area_id": area_id},
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": tournament_id},
    )
    return {"ok": True, "returned_to_pool": returned_to_pool}
