"""Операции HTTP с шаблонами правил категорий."""

from __future__ import annotations
import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Category, CategoryTemplate
from .common import _broadcast, _get_or_404
from .schemas import CategoryIn, CategoryTemplateIn

router = APIRouter()

def _template_dict(t: CategoryTemplate) -> dict[str, Any]:
    return {
        "id": t.id, "name": t.name, "format": t.format, "match_duration_sec": t.match_duration_sec,
        "timer_warning_sec": t.timer_warning_sec, "score_buttons": json.loads(t.score_buttons_json or "[]"),
        "warning_rules": json.loads(t.warning_rules_json or "[]"), "cumulative_warning_limit": t.cumulative_warning_limit,
        "group_target_size": t.group_target_size, "group_qualifiers": t.group_qualifiers, "swiss_rounds": t.swiss_rounds,
        "win_points": t.win_points, "draw_points": t.draw_points,
    }

def _fill_template(t: CategoryTemplate, data: CategoryIn) -> CategoryTemplate:
    t.format = data.format
    t.match_duration_sec = max(10, data.match_duration_sec)
    t.timer_warning_sec = max(0, data.timer_warning_sec)
    t.score_buttons_json = json.dumps(data.score_buttons, ensure_ascii=False)
    t.warning_rules_json = json.dumps(data.warning_rules, ensure_ascii=False)
    t.cumulative_warning_limit = max(0, data.cumulative_warning_limit)
    t.group_target_size = max(2, data.group_target_size)
    t.group_qualifiers = max(1, data.group_qualifiers)
    t.swiss_rounds = max(1, data.swiss_rounds)
    t.win_points = max(0, data.win_points)
    t.draw_points = max(0, data.draw_points)
    return t

@router.get("/category-templates")
def list_category_templates(db: Session = Depends(get_db)):
    return [_template_dict(t) for t in db.scalars(select(CategoryTemplate).order_by(CategoryTemplate.name)).all()]

@router.post("/category-templates")
async def save_category_template_values(data: CategoryTemplateIn, request: Request, db: Session = Depends(get_db)):
    if data.format not in {"knockout", "groups", "swiss", "round_robin"}:
        raise HTTPException(400, "Неизвестный формат")
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Укажите название шаблона")
    existing = db.scalar(select(CategoryTemplate).where(CategoryTemplate.name == name))
    t = _fill_template(existing or CategoryTemplate(name=name), data)
    t.name = name
    db.add(t)
    db.commit()
    await _broadcast(request, {"type":"templates_changed"})
    return _template_dict(t)

@router.post("/category-templates/from-category/{category_id}")
async def save_category_template(category_id: int, request: Request, db: Session = Depends(get_db)):
    c = _get_or_404(db, Category, category_id, "Категория")
    name = c.name.strip() or "Шаблон категории"
    data = CategoryTemplateIn(
        name=name, format=c.format, match_duration_sec=c.match_duration_sec, timer_warning_sec=c.timer_warning_sec,
        score_buttons=json.loads(c.score_buttons_json or "[]"), warning_rules=json.loads(c.warning_rules_json or "[]"),
        cumulative_warning_limit=c.cumulative_warning_limit, group_target_size=c.group_target_size,
        group_qualifiers=c.group_qualifiers, swiss_rounds=c.swiss_rounds, win_points=c.win_points, draw_points=c.draw_points,
    )
    existing = db.scalar(select(CategoryTemplate).where(CategoryTemplate.name == name))
    t = _fill_template(existing or CategoryTemplate(name=name), data)
    t.name = name
    db.add(t)
    db.commit()
    await _broadcast(request, {"type":"templates_changed"})
    return _template_dict(t)

@router.delete("/category-templates/{template_id}")
async def delete_category_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    t = _get_or_404(db, CategoryTemplate, template_id, "Шаблон")
    db.delete(t)
    db.commit()
    await _broadcast(request, {"type": "templates_changed"})
    return {"ok": True}
