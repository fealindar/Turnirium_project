"""Операции HTTP с категориями, составом и турнирными сетками."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..engine import (
    add_category_participant,
    audit,
    auto_assign_ready_matches,
    category_dict,
    clear_category_matches,
    json_load,
)
from ..exporter import write_json_export, write_pdf_export
from ..models import Area, Category, CategoryParticipant, Match, Participant, Tournament
from .common import _broadcast, _cp_dict, _get_or_404
from .schemas import CategoryIn, EnrollIn, SeedIn

router = APIRouter()


def _category_rule_values(data: CategoryIn) -> dict:
    """Возвращает нормализованные значения правил для ORM-модели категории."""

    return {
        "name": data.name,
        "format": data.format,
        "match_duration_sec": data.match_duration_sec,
        "timer_warning_sec": data.timer_warning_sec,
        "score_buttons_json": json.dumps(data.score_buttons, ensure_ascii=False),
        "warning_rules_json": json.dumps(data.warning_rules, ensure_ascii=False),
        "cumulative_warning_limit": data.cumulative_warning_limit,
        "group_target_size": data.group_target_size,
        "group_qualifiers": data.group_qualifiers,
        "swiss_rounds": data.swiss_rounds,
        "win_points": data.win_points,
        "draw_points": data.draw_points,
    }


def _real_match_started(db: Session, category_id: int) -> bool:
    """Проверяет, начался ли в категории хотя бы один реальный бой, исключая BYE."""

    count = db.scalar(
        select(func.count(Match.id)).where(
            Match.category_id == category_id,
            (Match.status == "in_progress")
            | ((Match.status == "finished") & (Match.result_reason != "BYE")),
        )
    ) or 0
    return bool(count)


def _rules_changed(category: Category, data: CategoryIn) -> bool:
    """Сравнивает спортивные правила семантически, не завися от форматирования JSON."""

    return any(
        (
            data.format != category.format,
            data.match_duration_sec != category.match_duration_sec,
            data.timer_warning_sec != category.timer_warning_sec,
            data.score_buttons != json_load(category.score_buttons_json, []),
            data.warning_rules != json_load(category.warning_rules_json, []),
            data.cumulative_warning_limit != category.cumulative_warning_limit,
            data.group_target_size != category.group_target_size,
            data.group_qualifiers != category.group_qualifiers,
            data.swiss_rounds != category.swiss_rounds,
            data.win_points != category.win_points,
            data.draw_points != category.draw_points,
        )
    )


def _structure_changed(category: Category, data: CategoryIn) -> bool:
    """Определяет изменения, при которых незапущенную сетку требуется пересоздать."""

    return any(
        (
            data.format != category.format,
            data.group_target_size != category.group_target_size,
            data.group_qualifiers != category.group_qualifiers,
            data.swiss_rounds != category.swiss_rounds,
        )
    )


def _apply_category_rules(category: Category, data: CategoryIn) -> None:
    """Копирует проверенные Pydantic-данные в ORM-модель."""

    for field, value in _category_rule_values(data).items():
        setattr(category, field, value)


@router.get("/tournaments/{tournament_id}/categories")
def list_categories(tournament_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Category)
        .where(Category.tournament_id == tournament_id)
        .order_by(Category.id)
    ).all()
    return [category_dict(category) for category in rows]


@router.post("/tournaments/{tournament_id}/categories")
async def create_category(
    tournament_id: int,
    data: CategoryIn,
    request: Request,
    db: Session = Depends(get_db),
):
    _get_or_404(db, Tournament, tournament_id, "Турнир")
    category = Category(tournament_id=tournament_id, **_category_rule_values(data))
    db.add(category)
    db.commit()
    await _broadcast(
        request,
        {"type": "categories_changed", "tournament_id": tournament_id},
    )
    return category_dict(category)


@router.put("/categories/{category_id}")
async def update_category(
    category_id: int,
    data: CategoryIn,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    started = _real_match_started(db, category.id)
    rule_changed = _rules_changed(category, data)
    structural_changed = _structure_changed(category, data)

    if started and rule_changed:
        raise HTTPException(
            409,
            "Правила и формат нельзя менять после начала первого поединка категории",
        )

    has_matches = bool(
        db.scalar(select(func.count(Match.id)).where(Match.category_id == category.id))
    )
    if structural_changed and has_matches:
        try:
            clear_category_matches(db, category)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        category.status = "draft"
        category.bracket_locked = False

    _apply_category_rules(category, data)

    if not started:
        editable_matches = db.scalars(
            select(Match).where(
                Match.category_id == category.id,
                Match.status.in_(["staged", "pending", "ready", "blocked"]),
            )
        ).all()
        for match in editable_matches:
            match.duration_ms = category.match_duration_sec * 1000
            match.remaining_ms = category.match_duration_sec * 1000

    db.commit()
    await _broadcast(
        request,
        {
            "type": "category_changed",
            "category_id": category.id,
            "tournament_id": category.tournament_id,
        },
    )
    if structural_changed:
        await _broadcast(
            request,
            {
                "type": "bracket_changed",
                "category_id": category.id,
                "tournament_id": category.tournament_id,
            },
        )
        await _broadcast(
            request,
            {"type": "schedule_changed", "tournament_id": category.tournament_id},
        )
    return category_dict(category)


@router.post("/categories/{category_id}/complete")
async def complete_category(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    active = db.scalar(
        select(func.count(Match.id)).where(
            Match.category_id == category.id,
            Match.status == "in_progress",
        )
    )
    if active:
        raise HTTPException(409, "В категории идет активный поединок")

    category.status = "completed"
    category.completed_at = datetime.now(timezone.utc)
    category_match_ids = select(Match.id).where(Match.category_id == category.id)
    areas = db.scalars(
        select(Area).where(Area.current_match_id.in_(category_match_ids))
    ).all()
    for area in areas:
        area.current_match_id = None

    audit(
        db,
        category.tournament_id,
        "CATEGORY_COMPLETED",
        "category",
        category.id,
    )
    db.commit()

    export_error = None
    try:
        write_pdf_export(db, category)
        write_json_export(db, category)
    except Exception as exc:
        # Экспорт не должен откатывать уже завершённую категорию: ошибку возвращаем UI.
        export_error = str(exc)

    await _broadcast(
        request,
        {
            "type": "categories_changed",
            "tournament_id": category.tournament_id,
            "category_id": category.id,
        },
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": category.tournament_id},
    )
    return {
        "ok": True,
        "exports": {
            "pdf": f"/api/categories/{category.id}/export.pdf",
            "json": f"/api/categories/{category.id}/export.json",
        },
        "export_error": export_error,
    }


@router.post("/categories/{category_id}/reopen")
async def reopen_category(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    has_matches = bool(
        db.scalar(select(func.count(Match.id)).where(Match.category_id == category.id))
    )
    category.status = "ready" if has_matches else "draft"
    category.completed_at = None
    auto_assign_ready_matches(db, category.tournament_id)
    db.commit()
    await _broadcast(
        request,
        {
            "type": "categories_changed",
            "tournament_id": category.tournament_id,
            "category_id": category.id,
        },
    )
    return {"ok": True}


@router.get("/categories/{category_id}/participants")
def category_participants(category_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(CategoryParticipant)
        .options(selectinload(CategoryParticipant.participant))
        .where(CategoryParticipant.category_id == category_id)
        .order_by(CategoryParticipant.seed_order, CategoryParticipant.id)
    ).all()
    return [_cp_dict(link) for link in rows]


@router.post("/categories/{category_id}/participants")
async def enroll(
    category_id: int,
    data: EnrollIn,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    participant = _get_or_404(db, Participant, data.participant_id, "Участник")
    if participant.tournament_id != category.tournament_id:
        raise HTTPException(400, "Участник из другого турнира")

    link = add_category_participant(db, category_id, participant.id)
    db.commit()
    await _broadcast(request, {"type": "category_changed", "category_id": category_id})
    return _cp_dict(link)


@router.put("/categories/{category_id}/seed")
async def update_seed(
    category_id: int,
    data: SeedIn,
    request: Request,
    db: Session = Depends(get_db),
):
    category = _get_or_404(db, Category, category_id, "Категория")
    if _real_match_started(db, category_id):
        raise HTTPException(409, "Посев нельзя менять после начала поединков категории")
    if len(data.cp_ids) != len(set(data.cp_ids)):
        raise HTTPException(400, "Посев содержит повторяющихся участников")

    participants = {
        link.id: link
        for link in db.scalars(
            select(CategoryParticipant).where(CategoryParticipant.category_id == category_id)
        ).all()
    }
    unknown = [link_id for link_id in data.cp_ids if link_id not in participants]
    if unknown:
        raise HTTPException(400, "Посев содержит участника из другой категории")

    requested = set(data.cp_ids)
    order = list(data.cp_ids) + [
        link_id for link_id in participants if link_id not in requested
    ]
    for seed_order, link_id in enumerate(order, 1):
        participants[link_id].seed_order = seed_order
    db.commit()

    has_matches = bool(
        db.scalar(select(func.count(Match.id)).where(Match.category_id == category_id))
    )
    if category.format == "knockout" and has_matches:
        generate_knockout(db, category, order)

    await _broadcast(
        request,
        {"type": "bracket_changed", "category_id": category_id},
    )
    return {"ok": True}
