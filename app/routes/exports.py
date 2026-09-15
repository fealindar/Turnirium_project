"""HTTP-маршруты выгрузок и компактного публичного статуса."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..engine import match_dict
from ..exporter import write_json_export, write_pdf_export
from ..models import Area, Category, Match, Tournament
from .common import _get_or_404

router = APIRouter()


def _next_area_match(db: Session, area: Area) -> Match | None:
    """Находит следующий готовый бой, не совпадающий с текущим."""

    query = (
        select(Match)
        .join(Category)
        .where(
            Match.area_id == area.id,
            Category.status != "completed",
            Match.status.in_(["ready", "pending"]),
        )
        .order_by(Match.queue_order, Match.id)
    )
    if area.current_match_id is not None:
        query = query.where(Match.id != area.current_match_id)
    return db.scalar(query)


def _export_response(path: Path, *, media_type: str, filename: str) -> FileResponse:
    """Создаёт единообразный ответ для скачивания сформированного файла."""

    return FileResponse(path, media_type=media_type, filename=filename)


@router.get("/tournaments/{tournament_id}/public")
def public_status(tournament_id: int, db: Session = Depends(get_db)):
    """Возвращает компактный список текущих и следующих боёв площадок."""

    _get_or_404(db, Tournament, tournament_id, "Турнир")
    areas = db.scalars(
        select(Area)
        .where(Area.tournament_id == tournament_id, Area.enabled.is_(True))
        .order_by(Area.id)
    ).all()

    rows = []
    for area in areas:
        current = db.get(Match, area.current_match_id) if area.current_match_id else None
        next_match = _next_area_match(db, area)
        rows.append(
            {
                "area": {"id": area.id, "name": area.name},
                "current": match_dict(current) if current else None,
                "next": match_dict(next_match) if next_match else None,
            }
        )
    return rows


@router.get("/tournaments/{tournament_id}/export.json")
def export_tournament_json(tournament_id: int, db: Session = Depends(get_db)):
    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    try:
        path = write_json_export(db, tournament)
    except Exception as exc:
        raise HTTPException(500, f"Не удалось сформировать JSON: {exc}") from exc
    return _export_response(
        path,
        media_type="application/json; charset=utf-8",
        filename=f"tournament_{tournament.id}_results.json",
    )


@router.get("/tournaments/{tournament_id}/export.pdf")
def export_tournament_pdf(tournament_id: int, db: Session = Depends(get_db)):
    tournament = _get_or_404(db, Tournament, tournament_id, "Турнир")
    try:
        path = write_pdf_export(db, tournament)
    except Exception as exc:
        raise HTTPException(500, f"Не удалось сформировать PDF: {exc}") from exc
    return _export_response(
        path,
        media_type="application/pdf",
        filename=f"tournament_{tournament.id}_results.pdf",
    )


@router.get("/categories/{category_id}/export.json")
def export_category_json(category_id: int, db: Session = Depends(get_db)):
    category = _get_or_404(db, Category, category_id, "Категория")
    try:
        path = write_json_export(db, category)
    except Exception as exc:
        raise HTTPException(500, f"Не удалось сформировать JSON: {exc}") from exc
    return _export_response(
        path,
        media_type="application/json; charset=utf-8",
        filename=f"category_{category.id}_results.json",
    )


@router.get("/categories/{category_id}/export.pdf")
def export_category_pdf(category_id: int, db: Session = Depends(get_db)):
    category = _get_or_404(db, Category, category_id, "Категория")
    try:
        path = write_pdf_export(db, category)
    except Exception as exc:
        raise HTTPException(500, f"Не удалось сформировать PDF: {exc}") from exc
    return _export_response(
        path,
        media_type="application/pdf",
        filename=f"category_{category.id}_results.pdf",
    )
