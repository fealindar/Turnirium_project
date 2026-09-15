"""Генерация и ручная перестройка этапов категории."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..engine import (
    generate_group_playoff,
    generate_groups,
    generate_knockout,
    generate_round_robin,
    generate_swiss_round,
    match_dict,
    rebuild_bracket_stage_from_slots,
    rebuild_groups_from_assignments,
    rebuild_swiss_round_from_slots,
    standings,
    start_group_stage,
    start_swiss_round,
)
from ..models import Category, CategoryParticipant, Match
from .common import _broadcast, _get_or_404
from .schemas import BracketLayoutIn, GroupLayoutIn, SwissLayoutIn

router = APIRouter()


@router.put("/categories/{category_id}/groups-layout")
async def update_groups_layout(
    category_id: int,
    data: GroupLayoutIn,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    if category.format != "groups":
        raise HTTPException(409, "Категория не использует групповой формат")
    try:
        rebuild_groups_from_assignments(db, category, data.groups)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await _broadcast(
        request,
        {
            "type": "bracket_changed",
            "category_id": category_id,
            "tournament_id": category.tournament_id,
        },
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": category.tournament_id},
    )
    return {"ok": True}


@router.post("/categories/{category_id}/groups-start")
async def groups_start(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    if category.format != "groups":
        raise HTTPException(409, "Категория не использует групповой формат")
    try:
        start_group_stage(db, category)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await _broadcast(
        request,
        {
            "type": "bracket_changed",
            "category_id": category_id,
            "tournament_id": category.tournament_id,
        },
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": category.tournament_id},
    )
    return {"ok": True}


@router.put("/categories/{category_id}/swiss-layout")
async def update_swiss_layout(
    category_id: int,
    data: SwissLayoutIn,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    if category.format != "swiss":
        raise HTTPException(409, "Категория не использует швейцарскую систему")
    try:
        rebuild_swiss_round_from_slots(db, category, data.cp_ids)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await _broadcast(
        request,
        {
            "type": "bracket_changed",
            "category_id": category_id,
            "tournament_id": category.tournament_id,
        },
    )
    return {"ok": True}


@router.post("/categories/{category_id}/swiss-start")
async def swiss_start(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    if category.format != "swiss":
        raise HTTPException(409, "Категория не использует швейцарскую систему")
    try:
        rows = start_swiss_round(db, category)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    round_no = rows[0].round_no if rows else None
    await _broadcast(
        request,
        {
            "type": "bracket_changed",
            "category_id": category_id,
            "tournament_id": category.tournament_id,
        },
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": category.tournament_id},
    )
    return {"ok": True, "round": round_no}


@router.put("/categories/{category_id}/bracket-layout")
async def update_bracket_layout(
    category_id: int,
    data: BracketLayoutIn,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    try:
        rebuild_bracket_stage_from_slots(db, category, data.stage, data.slot_cp_ids)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await _broadcast(
        request,
        {
            "type": "bracket_changed",
            "category_id": category_id,
            "tournament_id": category.tournament_id,
        },
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": category.tournament_id},
    )
    return {"ok": True}


@router.post("/categories/{category_id}/generate")
async def generate_category(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    generators = {
        "knockout": generate_knockout,
        "groups": generate_groups,
        "round_robin": generate_round_robin,
        "swiss": generate_swiss_round,
    }
    try:
        generators[category.format](db, category)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    await _broadcast(
        request,
        {
            "type": "bracket_changed",
            "category_id": category_id,
            "tournament_id": category.tournament_id,
        },
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": category.tournament_id},
    )
    return {"ok": True}


@router.post("/categories/{category_id}/group-playoff")
async def group_playoff(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    try:
        generate_group_playoff(db, category)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await _broadcast(
        request,
        {
            "type": "bracket_changed",
            "category_id": category_id,
            "tournament_id": category.tournament_id,
        },
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": category.tournament_id},
    )
    return {"ok": True}


@router.post("/categories/{category_id}/swiss-next")
async def swiss_next(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    try:
        rows = generate_swiss_round(db, category)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await _broadcast(
        request,
        {
            "type": "bracket_changed",
            "category_id": category_id,
            "tournament_id": category.tournament_id,
        },
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": category.tournament_id},
    )
    return {"round": rows[0].round_no if rows else None}


@router.get("/categories/{category_id}/matches")
def category_matches(category_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Match)
        .options(
            selectinload(Match.red_cp).selectinload(CategoryParticipant.participant),
            selectinload(Match.blue_cp).selectinload(CategoryParticipant.participant),
            selectinload(Match.category),
        )
        .where(Match.category_id == category_id)
        .order_by(Match.stage, Match.round_no, Match.match_no)
    ).all()
    return [match_dict(match) for match in rows]


@router.get("/categories/{category_id}/standings")
def category_standings(
    category_id: int,
    group: str | None = None,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    return standings(
        db,
        category_id,
        group,
        swiss_only=category.format == "swiss",
        round_robin_only=category.format == "round_robin",
    )
