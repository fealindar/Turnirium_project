"""Операции HTTP со списком участников и импортом данных."""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..engine import restore_participant, withdraw_participant
from ..models import CategoryParticipant, Match, Participant, Tournament
from .common import _broadcast, _get_or_404, _participant_dict
from .schemas import ParticipantImportIn, ParticipantIn, ParticipantStatusIn

router = APIRouter()

MAX_IMPORT_ROWS = 10_000


def _participants_query(tournament_id: int):
    """Возвращает единый порядок участников для UI и экспортов."""

    return (
        select(Participant)
        .where(Participant.tournament_id == tournament_id)
        .order_by(Participant.last_name, Participant.first_name, Participant.id)
    )


def _download_headers(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def _participant_key(
    last_name: str,
    first_name: str,
    club: str,
    city: str,
) -> tuple[str, str, str, str]:
    """Формирует регистронезависимый ключ дедупликации при импорте."""

    return tuple(
        value.strip().casefold()
        for value in (last_name, first_name, club, city)
    )


def _normalize_import_status(raw_value: str) -> str:
    """Нормализует поддерживаемые текстовые обозначения статуса участника."""

    value = raw_value.strip().casefold()
    if not value:
        return "active"
    if value in {"active", "активен", "участвует", "1", "yes", "да"}:
        return "active"
    if value in {"withdrawn", "выбыл", "inactive", "0", "no", "нет"}:
        return "withdrawn"
    raise ValueError(f"Неизвестный статус участника: {raw_value}")


@router.get("/tournaments/{tournament_id}/participants/export.csv")
def export_participants_csv(tournament_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, Tournament, tournament_id, "Турнир")
    rows = db.scalars(_participants_query(tournament_id)).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Фамилия", "Имя", "Клуб", "Город", "Статус"])
    for participant in rows:
        writer.writerow(
            [
                participant.last_name,
                participant.first_name,
                participant.club,
                participant.city,
                participant.status,
            ]
        )

    payload = "\ufeff" + output.getvalue()
    return Response(
        payload,
        media_type="text/csv; charset=utf-8",
        headers=_download_headers(f"participants_{tournament_id}.csv"),
    )


@router.get("/tournaments/{tournament_id}/participants/export.json")
def export_participants_json(tournament_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, Tournament, tournament_id, "Турнир")
    rows = db.scalars(_participants_query(tournament_id)).all()
    payload = {
        "schema_version": "1.0",
        "participants": [_participant_dict(participant) for participant in rows],
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers=_download_headers(f"participants_{tournament_id}.json"),
    )


def _import_participant_rows(content: str, filename: str) -> list[dict[str, str]]:
    """Разбирает CSV/JSON в единый внутренний формат без записи в БД."""

    text = content.lstrip("\ufeff").strip()
    if not text:
        return []

    if filename.lower().endswith(".json") or text.startswith(("[", "{")):
        payload = json.loads(text)
        rows = payload.get("participants", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("JSON должен содержать массив participants")
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            result.append(
                {
                    "last_name": str(
                        row.get("last_name") or row.get("Фамилия") or ""
                    ).strip(),
                    "first_name": str(
                        row.get("first_name") or row.get("Имя") or ""
                    ).strip(),
                    "club": str(row.get("club") or row.get("Клуб") or "").strip(),
                    "city": str(row.get("city") or row.get("Город") or "").strip(),
                    "status": str(
                        row.get("status") or row.get("Статус") or "active"
                    ).strip(),
                }
            )
        return result

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t,")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    result = []
    for row in reader:
        if not row:
            continue
        normalized = {
            (key or "").strip().casefold(): (value or "").strip()
            for key, value in row.items()
        }
        result.append(
            {
                "last_name": (
                    normalized.get("фамилия")
                    or normalized.get("last_name")
                    or normalized.get("surname")
                    or ""
                ),
                "first_name": (
                    normalized.get("имя")
                    or normalized.get("first_name")
                    or normalized.get("name")
                    or ""
                ),
                "club": normalized.get("клуб") or normalized.get("club") or "",
                "city": normalized.get("город") or normalized.get("city") or "",
                "status": (
                    normalized.get("статус")
                    or normalized.get("status")
                    or "active"
                ),
            }
        )
    return result


@router.get("/tournaments/{tournament_id}/participants")
def list_participants(tournament_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(_participants_query(tournament_id)).all()
    return [_participant_dict(participant) for participant in rows]


@router.post("/tournaments/{tournament_id}/participants")
async def create_participant(
    tournament_id: int,
    data: ParticipantIn,
    request: Request,
    db: Session = Depends(get_db),
):
    _get_or_404(db, Tournament, tournament_id, "Турнир")
    participant = Participant(
        tournament_id=tournament_id,
        first_name=data.first_name,
        last_name=data.last_name,
        club=data.club,
        city=data.city,
    )
    db.add(participant)
    db.commit()
    await _broadcast(
        request,
        {"type": "participants_changed", "tournament_id": tournament_id},
    )
    return _participant_dict(participant)


@router.post("/tournaments/{tournament_id}/participants/import")
async def import_participants(
    tournament_id: int,
    data: ParticipantImportIn,
    request: Request,
    db: Session = Depends(get_db),
):
    _get_or_404(db, Tournament, tournament_id, "Турнир")
    try:
        rows = _import_participant_rows(data.content, data.filename)
        if len(rows) > MAX_IMPORT_ROWS:
            raise ValueError(
                f"Один импорт не может содержать более {MAX_IMPORT_ROWS} участников"
            )
        for row_number, row in enumerate(rows, start=2):
            row["status"] = _normalize_import_status(row.get("status", "active"))
            if not row.get("last_name", "").strip():
                continue
            try:
                normalized = ParticipantIn(
                    last_name=row.get("last_name", ""),
                    first_name=row.get("first_name", ""),
                    club=row.get("club", ""),
                    city=row.get("city", ""),
                )
            except ValueError as exc:
                raise ValueError(f"Строка {row_number}: некорректные данные участника") from exc
            row.update(normalized.model_dump())
    except (csv.Error, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(400, f"Не удалось прочитать файл: {exc}") from exc

    existing = db.scalars(
        select(Participant).where(Participant.tournament_id == tournament_id)
    ).all()
    by_key = {
        _participant_key(
            participant.last_name,
            participant.first_name,
            participant.club,
            participant.city,
        ): participant
        for participant in existing
    }

    created = 0
    updated = 0
    skipped = 0
    try:
        for row in rows:
            last_name = row["last_name"].strip()
            if not last_name:
                skipped += 1
                continue

            first_name = row["first_name"].strip()
            club = row["club"].strip()
            city = row["city"].strip()
            status = row["status"]
            key = _participant_key(last_name, first_name, club, city)
            participant = by_key.get(key)

            if participant:
                if participant.status == status:
                    skipped += 1
                    continue
                if status == "withdrawn":
                    withdraw_participant(db, participant, commit=False)
                else:
                    restore_participant(db, participant, commit=False)
                updated += 1
                continue

            participant = Participant(
                tournament_id=tournament_id,
                last_name=last_name,
                first_name=first_name,
                club=club,
                city=city,
                status=status,
                active=status == "active",
            )
            db.add(participant)
            by_key[key] = participant
            created += 1
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc

    await _broadcast(
        request,
        {"type": "participants_changed", "tournament_id": tournament_id},
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": tournament_id},
    )
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


@router.put("/participants/{participant_id}")
async def update_participant(
    participant_id: int,
    data: ParticipantIn,
    request: Request,
    db: Session = Depends(get_db),
):
    participant = _get_or_404(db, Participant, participant_id, "Участник")
    participant.first_name = data.first_name
    participant.last_name = data.last_name
    participant.club = data.club
    participant.city = data.city
    db.commit()
    await _broadcast(
        request,
        {"type": "participants_changed", "tournament_id": participant.tournament_id},
    )
    await _broadcast(
        request,
        {"type": "bracket_changed", "tournament_id": participant.tournament_id},
    )
    return _participant_dict(participant)


@router.post("/participants/{participant_id}/status")
async def set_participant_status(
    participant_id: int,
    data: ParticipantStatusIn,
    request: Request,
    db: Session = Depends(get_db),
):
    participant = _get_or_404(db, Participant, participant_id, "Участник")
    try:
        if data.status == "withdrawn":
            withdraw_participant(db, participant)
        else:
            restore_participant(db, participant)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    await _broadcast(
        request,
        {"type": "participants_changed", "tournament_id": participant.tournament_id},
    )
    await _broadcast(
        request,
        {"type": "schedule_changed", "tournament_id": participant.tournament_id},
    )
    await _broadcast(
        request,
        {"type": "bracket_changed", "tournament_id": participant.tournament_id},
    )
    return _participant_dict(participant)


@router.delete("/participants/{participant_id}")
async def delete_participant(
    participant_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    participant = _get_or_404(db, Participant, participant_id, "Участник")
    tournament_id = participant.tournament_id
    linked_matches = db.scalar(
        select(func.count(Match.id))
        .join(
            CategoryParticipant,
            (Match.red_cp_id == CategoryParticipant.id)
            | (Match.blue_cp_id == CategoryParticipant.id),
        )
        .where(CategoryParticipant.participant_id == participant_id)
    )
    if linked_matches:
        raise HTTPException(409, "Участник уже присутствует в созданных поединках")

    db.delete(participant)
    db.commit()
    await _broadcast(
        request,
        {"type": "participants_changed", "tournament_id": tournament_id},
    )
    return {"ok": True}
