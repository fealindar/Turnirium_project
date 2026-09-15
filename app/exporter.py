from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .branding import load_branding
from .db import data_dir
from .engine import category_dict, match_dict, standings
from .models import Area, Category, CategoryParticipant, Match, Participant, Tournament

SCHEMA_VERSION = "1.3"


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return value.strip("._") or "results"


def exports_dir() -> Path:
    path = data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _participant(cp: CategoryParticipant) -> dict[str, Any]:
    p = cp.participant
    return {
        "category_participant_id": cp.id,
        "participant_id": p.id,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "name": p.display_name,
        "club": p.club,
        "city": p.city,
        "status": p.status,
        "seed_order": cp.seed_order,
        "group": cp.group_name,
        "cumulative_warnings": cp.cumulative_warnings,
        "disqualified": cp.disqualified,
    }


def category_snapshot(db: Session, category: Category) -> dict[str, Any]:
    cps = db.scalars(
        select(CategoryParticipant)
        .options(selectinload(CategoryParticipant.participant))
        .where(CategoryParticipant.category_id == category.id)
        .order_by(CategoryParticipant.seed_order, CategoryParticipant.id)
    ).all()
    matches = db.scalars(
        select(Match)
        .where(Match.category_id == category.id)
        .order_by(Match.stage, Match.round_no, Match.match_no)
    ).all()
    group_names = sorted({cp.group_name for cp in cps if cp.group_name})
    group_tables = {name: standings(db, category.id, name) for name in group_names}
    overall_table = standings(
        db, category.id,
        swiss_only=(category.format == "swiss"),
        round_robin_only=(category.format == "round_robin"),
    )
    swiss_table = overall_table if category.format == "swiss" else []
    round_robin_table = overall_table if category.format == "round_robin" else []
    return {
        "category": category_dict(category),
        "participants": [_participant(cp) for cp in cps],
        "group_tables": group_tables,
        "standings": overall_table,
        "swiss_standings": swiss_table,
        "round_robin_standings": round_robin_table,
        "matches": [match_dict(m) for m in matches],
    }


def tournament_snapshot(db: Session, tournament: Tournament) -> dict[str, Any]:
    categories = db.scalars(
        select(Category).where(Category.tournament_id == tournament.id).order_by(Category.id)
    ).all()
    areas = db.scalars(select(Area).where(Area.tournament_id == tournament.id).order_by(Area.id)).all()
    participants = db.scalars(
        select(Participant).where(Participant.tournament_id == tournament.id).order_by(Participant.last_name, Participant.first_name)
    ).all()
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "application": load_branding()["app_name"],
        "tournament": {
            "id": tournament.id,
            "name": tournament.name,
            "venue": tournament.venue,
            "event_date": tournament.event_date,
            "status": tournament.status,
            "created_at": _iso(tournament.created_at),
            "completed_at": _iso(tournament.completed_at),
        },
        "areas": [
            {"id": a.id, "name": a.name, "enabled": a.enabled, "current_match_id": a.current_match_id}
            for a in areas
        ],
        "participants": [
            {
                "id": p.id,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "name": p.display_name,
                "club": p.club,
                "city": p.city,
                "status": p.status,
            }
            for p in participants
        ],
        "categories": [category_snapshot(db, c) for c in categories],
    }


def category_export_snapshot(db: Session, category: Category) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "application": load_branding()["app_name"],
        "tournament": {
            "id": category.tournament.id,
            "name": category.tournament.name,
            "venue": category.tournament.venue,
            "event_date": category.tournament.event_date,
        },
        **category_snapshot(db, category),
    }


def write_json_export(db: Session, entity: Tournament | Category) -> Path:
    if isinstance(entity, Tournament):
        payload = tournament_snapshot(db, entity)
        stem = f"tournament_{entity.id}_results"
    else:
        payload = category_export_snapshot(db, entity)
        stem = f"category_{entity.id}_results"
    path = exports_dir() / f"{_safe_filename(stem)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _register_fonts() -> tuple[str, str]:
    regular_candidates = [
        os.path.join(os.environ.get("WINDIR", r"C:\\Windows"), "Fonts", "arial.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    bold_candidates = [
        os.path.join(os.environ.get("WINDIR", r"C:\\Windows"), "Fonts", "arialbd.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    regular = next((p for p in regular_candidates if Path(p).exists()), None)
    bold = next((p for p in bold_candidates if Path(p).exists()), None)
    if not regular:
        raise RuntimeError("Не найден системный TrueType-шрифт для формирования PDF")
    if not bold:
        bold = regular
    if "LTFont" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("LTFont", regular))
    if "LTFontBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("LTFontBold", bold))
    return "LTFont", "LTFontBold"


def _styles():
    regular, bold = _register_fonts()
    base = getSampleStyleSheet()
    return {
        "regular": regular,
        "bold": bold,
        "title": ParagraphStyle("LTTitle", parent=base["Title"], fontName=bold, fontSize=20, leading=24, textColor=colors.HexColor("#183153"), spaceAfter=10),
        "h1": ParagraphStyle("LTH1", parent=base["Heading1"], fontName=bold, fontSize=14, leading=17, textColor=colors.HexColor("#204e82"), spaceBefore=8, spaceAfter=7),
        "h2": ParagraphStyle("LTH2", parent=base["Heading2"], fontName=bold, fontSize=11, leading=14, textColor=colors.HexColor("#334155"), spaceBefore=6, spaceAfter=5),
        "body": ParagraphStyle("LTBody", parent=base["BodyText"], fontName=regular, fontSize=8.5, leading=11),
        "small": ParagraphStyle("LTSmall", parent=base["BodyText"], fontName=regular, fontSize=7, leading=9, textColor=colors.HexColor("#52606d")),
        "center": ParagraphStyle("LTCenter", parent=base["BodyText"], fontName=regular, fontSize=8, leading=10, alignment=TA_CENTER),
    }


def _p(text: Any, style) -> Paragraph:
    value = str(text if text not in (None, "") else "-")
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(value, style)


def _table(data, widths, styles, header=True):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), styles["regular"]),
        ("FONTSIZE", (0, 0), (-1, -1), 7.2),
        ("LEADING", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7dee8")),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf1f8")),
            ("FONTNAME", (0, 0), (-1, 0), styles["bold"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#183153")),
        ]
    for row in range(1 if header else 0, len(data)):
        if row % 2 == 0:
            commands.append(("BACKGROUND", (0, row), (-1, row), colors.HexColor("#f9fbfd")))
    t.setStyle(TableStyle(commands))
    return t



def _short(value: str | None, limit: int = 18) -> str:
    value = (value or "BYE").strip()
    return value if len(value) <= limit else value[: max(1, limit - 1)] + "…"


def _match_card_drawing(d: Drawing, x: float, y: float, w: float, h: float, match: dict[str, Any], regular: str, bold: str, accent: str = "#d8e2ee") -> None:
    d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=colors.HexColor("#ffffff"), strokeColor=colors.HexColor(accent), strokeWidth=.7))
    mid = y + h / 2
    d.add(Line(x, mid, x + w, mid, strokeColor=colors.HexColor("#e7edf4"), strokeWidth=.5))
    red = match.get("red") or {}
    blue = match.get("blue") or {}
    red_name = _short(red.get("name"), 17)
    blue_name = _short(blue.get("name"), 17)
    fs = max(5.0, min(6.4, w / 17.5))
    d.add(String(x + 4, y + h - 10, red_name, fontName=bold if match.get("winner_cp_id") == red.get("cp_id") else regular, fontSize=fs, fillColor=colors.HexColor("#9f2630")))
    d.add(String(x + w - 5, y + h - 10, str(match.get("red_score", 0)), fontName=bold, fontSize=fs, textAnchor="end", fillColor=colors.HexColor("#334155")))
    d.add(String(x + 4, y + 5, blue_name, fontName=bold if match.get("winner_cp_id") == blue.get("cp_id") else regular, fontSize=fs, fillColor=colors.HexColor("#245da5")))
    d.add(String(x + w - 5, y + 5, str(match.get("blue_score", 0)), fontName=bold, fontSize=fs, textAnchor="end", fillColor=colors.HexColor("#334155")))


def _mirrored_bracket_drawing(matches: list[dict[str, Any]], styles, max_width: float = 760, max_height: float = 330) -> Drawing | None:
    tree = [m for m in matches if not m.get("is_third_place")]
    bronze = next((m for m in matches if m.get("is_third_place")), None)
    if not tree:
        return None
    rounds = sorted({int(m["round_no"]) for m in tree})
    last = rounds[-1]
    if not last:
        return None
    column_count = max(1, (len(rounds) - 1) * 2 + 1)
    gap = 8.0
    col_w = max(66.0, (max_width - gap * (column_count - 1)) / column_count)
    width = col_w * column_count + gap * (column_count - 1)
    first = sorted([m for m in tree if m["round_no"] == 1], key=lambda x: x["match_no"])
    side_first = max(1, (len(first) + 1) // 2)
    height = min(max_height, max(190.0, side_first * 62.0 + (58.0 if bronze else 0)))
    d = Drawing(width, height)
    card_h = 32.0
    pos: dict[int, tuple[float, float, str]] = {}

    def y_positions(count: int, reserve_bottom: float = 0.0) -> list[float]:
        if count <= 0:
            return []
        usable = height - reserve_bottom
        step = usable / count
        return [usable - (i + .5) * step - card_h / 2 for i in range(count)]

    for r in rounds:
        if r == last:
            continue
        all_rows = sorted([m for m in tree if m["round_no"] == r], key=lambda x: x["match_no"])
        half = (len(all_rows) + 1) // 2
        left_rows, right_rows = all_rows[:half], all_rows[half:]
        left_x = (r - 1) * (col_w + gap)
        right_x = width - col_w - (r - 1) * (col_w + gap)
        for m, y in zip(left_rows, y_positions(len(left_rows))):
            pos[m["id"]] = (left_x, y, "left")
        for m, y in zip(right_rows, y_positions(len(right_rows))):
            pos[m["id"]] = (right_x, y, "right")

    final = next((m for m in tree if m["round_no"] == last), None)
    center_x = (width - col_w) / 2
    final_y = height / 2 - card_h / 2 + (20 if bronze else 0)
    if final:
        pos[final["id"]] = (center_x, final_y, "center")

    # Сначала рисуем связи, чтобы карточки оставались чёткими поверх линий.
    by_id = {m["id"]: m for m in tree}
    for m in tree:
        nxt_id = m.get("next_match_id")
        if not nxt_id or m["id"] not in pos or nxt_id not in pos:
            continue
        sx, sy, side = pos[m["id"]]
        tx, ty, _ = pos[nxt_id]
        if side == "right":
            x1, x2 = sx, tx + col_w
        else:
            x1, x2 = sx + col_w, tx
        y1, y2 = sy + card_h / 2, ty + card_h / 2
        mx = (x1 + x2) / 2
        for x0, yy0, x3, yy3 in [(x1, y1, mx, y1), (mx, y1, mx, y2), (mx, y2, x2, y2)]:
            d.add(Line(x0, yy0, x3, yy3, strokeColor=colors.HexColor("#9aaabd"), strokeWidth=.8))

    for m in tree:
        if m["id"] in pos:
            x, y, _ = pos[m["id"]]
            _match_card_drawing(d, x, y, col_w, card_h, m, styles["regular"], styles["bold"])

    if bronze:
        bronze_y = max(4.0, final_y - 58.0)
        d.add(String(center_x + col_w / 2, bronze_y + card_h + 5, "За 3-е место", fontName=styles["bold"], fontSize=6.3, textAnchor="middle", fillColor=colors.HexColor("#806321")))
        _match_card_drawing(d, center_x, bronze_y, col_w, card_h, bronze, styles["regular"], styles["bold"], accent="#d7bc72")
    return d


def _category_story(db: Session, category: Category, styles) -> list[Any]:
    story: list[Any] = []
    snap = category_snapshot(db, category)
    fmt = {"knockout": "Олимпийская", "groups": "Группы + плей-офф", "swiss": "Швейцарская", "round_robin": "Все со всеми"}.get(category.format, category.format)
    story += [
        Paragraph(category.name, styles["h1"]),
        _p(f"Формат: {fmt} | Статус: {category.status} | Длительность боя: {category.match_duration_sec} сек.", styles["small"]),
        Spacer(1, 3 * mm),
    ]

    elimination = [m for m in snap["matches"] if m["stage"] in ("knockout", "playoff")]
    if elimination:
        rows = snap.get("standings") or []
        if rows:
            story.append(Paragraph("Итоговая таблица", styles["h2"]))
            data = [["#", "Участник", "Клуб / город", "Этап", "Бои", "Поб.", "Счёт", "Последний бой"]]
            for r in rows:
                last = r.get("last_score") or "-"
                data.append([
                    r["place"],
                    _p(r["name"], styles["body"]),
                    _p(" · ".join(x for x in [r.get("club"), r.get("city")] if x), styles["small"]),
                    _p(r.get("stage_label") or "-", styles["small"]),
                    r.get("played", 0),
                    r.get("wins", 0),
                    f'{r.get("for", 0)}:{r.get("against", 0)}',
                    _p(last, styles["small"]),
                ])
            story.append(_table(data, [9*mm, 42*mm, 42*mm, 31*mm, 12*mm, 12*mm, 18*mm, 22*mm], styles))
            story.append(Spacer(1, 3 * mm))
        bracket = _mirrored_bracket_drawing(elimination, styles)
        if bracket:
            story.append(Paragraph("Турнирная сетка", styles["h2"]))
            story.append(bracket)
            story.append(Spacer(1, 3 * mm))

    group_tables = snap["group_tables"]
    if group_tables:
        story.append(Paragraph("Групповые таблицы", styles["h2"]))
        for name, rows in group_tables.items():
            story.append(_p(f"Группа {name}", styles["body"]))
            data = [["#", "Участник", "Клуб / город", "Бои", "Поб.", "Нич.", "Турн. очки", "+/-", "Пред."]]
            for r in rows:
                data.append([
                    r["place"], _p(r["name"], styles["body"]), _p(" · ".join(x for x in [r.get("club"), r.get("city")] if x), styles["small"]),
                    r["played"], r["wins"], r.get("draws", 0), r["points"], r["diff"], r["warnings"],
                ])
            story.append(_table(data, [9*mm, 40*mm, 40*mm, 12*mm, 12*mm, 12*mm, 20*mm, 13*mm, 13*mm], styles))
            story.append(Spacer(1, 3 * mm))

    if category.format == "swiss":
        rows = snap["swiss_standings"]
        if rows:
            story.append(Paragraph("Итоговая таблица Swiss", styles["h2"]))
            data = [["#", "Участник", "Клуб / город", "Бои", "Поб.", "Нич.", "Турн. очки", "+/-", "Пред."]]
            for r in rows:
                data.append([r["place"], _p(r["name"], styles["body"]), _p(" · ".join(x for x in [r.get("club"), r.get("city")] if x), styles["small"]), r["played"], r["wins"], r.get("draws", 0), r["points"], r["diff"], r["warnings"]])
            story.append(_table(data, [9*mm, 40*mm, 40*mm, 12*mm, 12*mm, 12*mm, 20*mm, 13*mm, 13*mm], styles))
            story.append(Spacer(1, 3 * mm))

    if category.format == "round_robin":
        rows = snap["round_robin_standings"]
        if rows:
            story.append(Paragraph("Итоговая таблица «все со всеми»", styles["h2"]))
            data = [["#", "Участник", "Клуб / город", "Бои", "Поб.", "Нич.", "Турн. очки", "+/-", "Пред."]]
            for r in rows:
                data.append([r["place"], _p(r["name"], styles["body"]), _p(" · ".join(x for x in [r.get("club"), r.get("city")] if x), styles["small"]), r["played"], r["wins"], r.get("draws", 0), r["points"], r["diff"], r["warnings"]])
            story.append(_table(data, [9*mm, 40*mm, 40*mm, 12*mm, 12*mm, 12*mm, 20*mm, 13*mm, 13*mm], styles))
            story.append(Spacer(1, 3 * mm))

    matches = snap["matches"]
    if matches:
        story.append(Paragraph("Результаты поединков", styles["h2"]))
        data = [["#", "Этап", "Красный", "Счёт", "Синий", "Победитель", "Результат"]]
        for m in matches:
            stage = m["stage"]
            if m.get("is_third_place"):
                stage_label = "За 3-е место"
            elif stage == "group":
                stage_label = f'Гр. {m.get("group_name") or "-"}'
            elif stage == "swiss":
                stage_label = f'Swiss {m["round_no"]}'
            elif stage == "round_robin":
                stage_label = "Все со всеми"
            elif stage == "playoff":
                stage_label = f'ПО {m["round_no"]}'
            else:
                stage_label = f'Раунд {m["round_no"]}'
            winner = m["red"]["name"] if m.get("red") and m.get("winner_cp_id") == m["red"].get("cp_id") else m["blue"]["name"] if m.get("blue") and m.get("winner_cp_id") == m["blue"].get("cp_id") else "-"
            reason = {
                "POINTS": "По счёту", "TECHNICAL_LOSS": "Тех. поражение", "WARNING_FORFEIT": "По предупреждениям",
                "DISQUALIFICATION": "Дисквалификация", "WITHDRAWAL": "Выбыл", "BYE": "Автопроход",
            }.get(m.get("reason"), m.get("reason") or "-")
            data.append([
                m["match_no"], stage_label, _p(m.get("red", {}).get("name") if m.get("red") else "BYE", styles["small"]),
                f'{m["red_score"]}:{m["blue_score"]}', _p(m.get("blue", {}).get("name") if m.get("blue") else "BYE", styles["small"]),
                _p(winner, styles["small"]), _p(reason, styles["small"]),
            ])
        story.append(_table(data, [10*mm, 24*mm, 49*mm, 17*mm, 49*mm, 44*mm, 38*mm], styles))
        story.append(Spacer(1, 4 * mm))

    return story


def _page_footer(canvas, doc, regular_font: str):
    canvas.saveState()
    canvas.setFont(regular_font, 7)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    brand = load_branding()
    footer = f'{brand["app_name"]} - экспорт результатов'
    if brand.get("developer_club_name"):
        footer += f' · {brand["developer_club_name"]}'
    canvas.drawString(12 * mm, 7 * mm, footer)
    canvas.drawRightString(landscape(A4)[0] - 12 * mm, 7 * mm, f"Страница {doc.page}")
    canvas.restoreState()


def write_pdf_export(db: Session, entity: Tournament | Category) -> Path:
    styles = _styles()
    if isinstance(entity, Tournament):
        stem = f"tournament_{entity.id}_results"
        title = entity.name
        subtitle = "Итоговый протокол турнира"
        categories = db.scalars(select(Category).where(Category.tournament_id == entity.id).order_by(Category.id)).all()
        meta = " · ".join(x for x in [entity.event_date, entity.venue] if x)
    else:
        stem = f"category_{entity.id}_results"
        title = entity.name
        subtitle = f"Результаты категории · {entity.tournament.name}"
        categories = [entity]
        meta = " · ".join(x for x in [entity.tournament.event_date, entity.tournament.venue] if x)

    path = exports_dir() / f"{_safe_filename(stem)}.pdf"
    doc = SimpleDocTemplate(
        str(path), pagesize=landscape(A4), leftMargin=12*mm, rightMargin=12*mm,
        topMargin=12*mm, bottomMargin=12*mm, title=title, author=load_branding()["app_name"],
    )
    story: list[Any] = [Paragraph(title, styles["title"]), _p(subtitle, styles["body"])]
    if meta:
        story += [_p(meta, styles["small"]), Spacer(1, 4*mm)]
    for idx, category in enumerate(categories):
        if idx:
            story.append(PageBreak())
        story.extend(_category_story(db, category, styles))
    if not categories:
        story.append(_p("Категории отсутствуют.", styles["body"]))
    doc.build(story, onFirstPage=lambda c, d: _page_footer(c, d, styles["regular"]), onLaterPages=lambda c, d: _page_footer(c, d, styles["regular"]))
    return path
