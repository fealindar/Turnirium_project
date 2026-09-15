"""Входные модели API и централизованная валидация данных."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


MatchSide = Literal["red", "blue"]
ParticipantStatus = Literal["active", "withdrawn"]
ResultReason = Literal[
    "POINTS",
    "DRAW",
    "TECHNICAL_LOSS",
    "WARNING_FORFEIT",
    "DISQUALIFICATION",
    "WITHDRAWAL",
]
CategoryFormat = Literal["knockout", "groups", "swiss", "round_robin"]


class TournamentIn(BaseModel):
    name: str = Field(default="Новый Турнир", min_length=1, max_length=200)
    venue: str = Field(default="", max_length=200)
    event_date: str = Field(default="", max_length=20)

    @field_validator("name", "venue", "event_date")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Название турнира не может быть пустым")
        return value


class AreaIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ParticipantIn(BaseModel):
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    club: str = Field(default="", max_length=160)
    city: str = Field(default="", max_length=160)

    @field_validator("first_name", "last_name", "club", "city")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    format: CategoryFormat = "knockout"
    match_duration_sec: int = Field(default=120, ge=10, le=3600)
    timer_warning_sec: int = Field(default=10, ge=0, le=3600)
    score_buttons: list[dict[str, Any]] = Field(default_factory=lambda: [
        {"label": "-1", "delta": -1},
        {"label": "+1", "delta": 1},
        {"label": "+2", "delta": 2},
        {"label": "+3", "delta": 3},
    ])
    warning_rules: list[dict[str, Any]] = Field(default_factory=lambda: [
        {"number": 1, "action": "warning", "delta": 0},
        {"number": 2, "action": "score_penalty", "delta": -2},
        {"number": 3, "action": "forfeit", "delta": 0},
    ])
    cumulative_warning_limit: int = Field(default=4, ge=0, le=100)
    group_target_size: int = Field(default=4, ge=2, le=64)
    group_qualifiers: int = Field(default=2, ge=1, le=64)
    swiss_rounds: int = Field(default=4, ge=1, le=50)
    win_points: int = Field(default=3, ge=0, le=100)
    draw_points: int = Field(default=1, ge=0, le=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название категории не может быть пустым")
        return value

    @field_validator("score_buttons")
    @classmethod
    def validate_score_buttons(cls, items: list[dict[str, Any]]) -> list[dict[str, int | str]]:
        if not 1 <= len(items) <= 12:
            raise ValueError("Должно быть от 1 до 12 кнопок счёта")
        normalized: list[dict[str, int | str]] = []
        for item in items:
            label = str(item.get("label", "")).strip()
            if not label or len(label) > 16:
                raise ValueError("Подпись кнопки счёта должна содержать от 1 до 16 символов")
            try:
                delta = int(item["delta"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Для каждой кнопки счёта требуется целое значение delta") from exc
            if not -100 <= delta <= 100:
                raise ValueError("Изменение счёта должно быть в диапазоне от -100 до 100")
            normalized.append({"label": label, "delta": delta})
        return normalized

    @field_validator("warning_rules")
    @classmethod
    def validate_warning_rules(cls, items: list[dict[str, Any]]) -> list[dict[str, int | str]]:
        if len(items) > 20:
            raise ValueError("Допускается не более 20 правил предупреждений")
        normalized: list[dict[str, int | str]] = []
        numbers: set[int] = set()
        allowed_actions = {"warning", "score_penalty", "forfeit"}
        for item in items:
            try:
                number = int(item["number"])
                delta = int(item.get("delta", 0) or 0)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Номер предупреждения и delta должны быть целыми числами") from exc
            action = str(item.get("action", "warning")).strip()
            if number < 1 or number > 100 or number in numbers:
                raise ValueError("Номера предупреждений должны быть уникальными числами от 1 до 100")
            if action not in allowed_actions:
                raise ValueError("Неизвестное действие правила предупреждения")
            if not -100 <= delta <= 100:
                raise ValueError("Штраф по счёту должен быть в диапазоне от -100 до 100")
            numbers.add(number)
            normalized.append({"number": number, "action": action, "delta": delta})
        return normalized

    @model_validator(mode="after")
    def validate_related_values(self) -> "CategoryIn":
        if self.timer_warning_sec > self.match_duration_sec:
            raise ValueError("Предупреждение таймера не может быть позже окончания боя")
        if self.format == "groups" and self.group_qualifiers >= self.group_target_size:
            raise ValueError("Из группы должно выходить меньше бойцов, чем её целевой размер")
        return self


class CategoryTemplateIn(CategoryIn):
    pass


class SeedIn(BaseModel):
    cp_ids: list[int]


class EnrollIn(BaseModel):
    participant_id: int


class ScoreIn(BaseModel):
    side: MatchSide
    delta: int = Field(ge=-100, le=100)


class SideIn(BaseModel):
    side: MatchSide


class FinishIn(BaseModel):
    winner_cp_id: int | None = None
    reason: ResultReason = "POINTS"


class MatchCorrectionIn(BaseModel):
    red_score: int = Field(ge=-10000, le=10000)
    blue_score: int = Field(ge=-10000, le=10000)
    red_warnings: int = Field(default=0, ge=0, le=1000)
    blue_warnings: int = Field(default=0, ge=0, le=1000)
    winner_cp_id: int | None = None
    reason: ResultReason = "POINTS"


class ParticipantStatusIn(BaseModel):
    status: ParticipantStatus


class ParticipantDetailsIn(BaseModel):
    fee_paid: bool = False
    comment: str = Field(default="", max_length=4000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        return value.strip()


class ParticipantImportIn(BaseModel):
    filename: str = Field(default="participants.csv", max_length=255)
    content: str = Field(max_length=5_000_000)


class SwissLayoutIn(BaseModel):
    cp_ids: list[int | None]


class ClearDatabaseIn(BaseModel):
    confirmation: str
    preserve_templates: bool = True


class ScheduleSettingsIn(BaseModel):
    avoid_consecutive_matches: bool = True
    preferred_match_gap: int = Field(default=1, ge=1, le=10)


class AssignIn(BaseModel):
    match_id: int
    area_id: int | None = None
    position: int | None = None


class ScheduleUnitAssignIn(BaseModel):
    category_id: int
    area_id: int
    group_name: str = Field(default="", max_length=32)


class ReorderIn(BaseModel):
    match_ids: list[int]


class GroupLayoutIn(BaseModel):
    groups: dict[str, list[int]]


class BracketLayoutIn(BaseModel):
    stage: str
    slot_cp_ids: list[int | None]


class TimerSetIn(BaseModel):
    seconds: int = Field(ge=0, le=86400)


class DatabaseSelectIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
