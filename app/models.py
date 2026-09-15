from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


DEFAULT_SCORE_BUTTONS_JSON = (
    '[{"label":"-1","delta":-1},{"label":"+1","delta":1},'
    '{"label":"+2","delta":2},{"label":"+3","delta":3}]'
)
DEFAULT_WARNING_RULES_JSON = (
    '[{"number":1,"action":"warning","delta":0},'
    '{"number":2,"action":"score_penalty","delta":-2},'
    '{"number":3,"action":"forfeit","delta":0}]'
)
DEFAULT_TEMPLATE_WARNING_RULES_JSON = '[{"number":1,"action":"warning","delta":0}]'


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Турнир")
    venue: Mapped[str] = mapped_column(String(200), default="")
    event_date: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(24), default="active")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    avoid_consecutive_matches: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_match_gap: Mapped[int] = mapped_column(Integer, default=1)

    categories = relationship("Category", back_populates="tournament", cascade="all, delete-orphan")
    participants = relationship("Participant", back_populates="tournament", cascade="all, delete-orphan")
    areas = relationship("Area", back_populates="tournament", cascade="all, delete-orphan")


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    first_name: Mapped[str] = mapped_column(String(100), default="")
    last_name: Mapped[str] = mapped_column(String(100))
    club: Mapped[str] = mapped_column(String(160), default="")
    city: Mapped[str] = mapped_column(String(160), default="")
    fee_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Статусы: active — участвует, withdrawn — выбыл.
    status: Mapped[str] = mapped_column(String(24), default="active")

    tournament = relationship("Tournament", back_populates="participants")
    category_links = relationship("CategoryParticipant", back_populates="participant", cascade="all, delete-orphan")

    @property
    def display_name(self) -> str:
        return f"{self.last_name} {self.first_name}".strip()


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    # Форматы: knockout — олимпийка, groups — группы + плей-офф,
    # swiss — швейцарская система, round_robin — все со всеми.
    format: Mapped[str] = mapped_column(String(32), default="knockout")
    match_duration_sec: Mapped[int] = mapped_column(Integer, default=120)
    timer_warning_sec: Mapped[int] = mapped_column(Integer, default=10)
    score_buttons_json: Mapped[str] = mapped_column(Text, default=DEFAULT_SCORE_BUTTONS_JSON)
    warning_rules_json: Mapped[str] = mapped_column(Text, default=DEFAULT_WARNING_RULES_JSON)
    cumulative_warning_limit: Mapped[int] = mapped_column(Integer, default=4)
    group_target_size: Mapped[int] = mapped_column(Integer, default=4)
    group_qualifiers: Mapped[int] = mapped_column(Integer, default=2)
    swiss_rounds: Mapped[int] = mapped_column(Integer, default=4)
    win_points: Mapped[int] = mapped_column(Integer, default=3)
    draw_points: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    bracket_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tournament = relationship("Tournament", back_populates="categories")
    participants = relationship("CategoryParticipant", back_populates="category", cascade="all, delete-orphan")
    matches = relationship("Match", back_populates="category", cascade="all, delete-orphan")


class CategoryTemplate(Base):
    __tablename__ = "category_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    # Форматы: knockout — олимпийка, groups — группы + плей-офф,
    # swiss — швейцарская система, round_robin — все со всеми.
    format: Mapped[str] = mapped_column(String(32), default="knockout")
    match_duration_sec: Mapped[int] = mapped_column(Integer, default=120)
    timer_warning_sec: Mapped[int] = mapped_column(Integer, default=10)
    score_buttons_json: Mapped[str] = mapped_column(Text, default=DEFAULT_SCORE_BUTTONS_JSON)
    warning_rules_json: Mapped[str] = mapped_column(Text, default=DEFAULT_TEMPLATE_WARNING_RULES_JSON)
    cumulative_warning_limit: Mapped[int] = mapped_column(Integer, default=4)
    group_target_size: Mapped[int] = mapped_column(Integer, default=4)
    group_qualifiers: Mapped[int] = mapped_column(Integer, default=2)
    swiss_rounds: Mapped[int] = mapped_column(Integer, default=4)
    win_points: Mapped[int] = mapped_column(Integer, default=3)
    draw_points: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CategoryParticipant(Base):
    __tablename__ = "category_participants"
    __table_args__ = (UniqueConstraint("category_id", "participant_id", name="uq_category_participant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"), index=True)
    seed_order: Mapped[int] = mapped_column(Integer, default=0)
    cumulative_warnings: Mapped[int] = mapped_column(Integer, default=0)
    disqualified: Mapped[bool] = mapped_column(Boolean, default=False)
    group_name: Mapped[str] = mapped_column(String(32), default="")

    category = relationship("Category", back_populates="participants")
    participant = relationship("Participant", back_populates="category_links")


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    current_match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"), nullable=True)

    tournament = relationship("Tournament", back_populates="areas")
    queued_matches = relationship("Match", foreign_keys="Match.area_id", back_populates="area")
    current_match = relationship("Match", foreign_keys=[current_match_id], post_update=True)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    # Этап: олимпийка, группа, плей-офф, швейцарка или все со всеми.
    stage: Mapped[str] = mapped_column(String(32), default="knockout")
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    match_no: Mapped[int] = mapped_column(Integer, default=1)
    group_name: Mapped[str] = mapped_column(String(32), default="")
    is_third_place: Mapped[bool] = mapped_column(Boolean, default=False)

    red_cp_id: Mapped[int | None] = mapped_column(ForeignKey("category_participants.id", ondelete="SET NULL"), nullable=True)
    blue_cp_id: Mapped[int | None] = mapped_column(ForeignKey("category_participants.id", ondelete="SET NULL"), nullable=True)
    red_score: Mapped[int] = mapped_column(Integer, default=0)
    blue_score: Mapped[int] = mapped_column(Integer, default=0)
    red_warnings: Mapped[int] = mapped_column(Integer, default=0)
    blue_warnings: Mapped[int] = mapped_column(Integer, default=0)
    winner_cp_id: Mapped[int | None] = mapped_column(ForeignKey("category_participants.id", ondelete="SET NULL"), nullable=True)
    result_reason: Mapped[str] = mapped_column(String(64), default="")
    # Состояние: заблокирован, ожидает, готов, идёт или завершён.
    status: Mapped[str] = mapped_column(String(24), default="pending")

    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"), nullable=True, index=True)
    queue_order: Mapped[int] = mapped_column(Integer, default=0)

    duration_ms: Mapped[int] = mapped_column(Integer, default=120000)
    remaining_ms: Mapped[int] = mapped_column(Integer, default=120000)
    timer_running: Mapped[bool] = mapped_column(Boolean, default=False)
    timer_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timer_revision: Mapped[int] = mapped_column(Integer, default=0)

    next_match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"), nullable=True)
    # Сторона следующего боя: red или blue.
    next_slot: Mapped[str] = mapped_column(String(8), default="")
    source_red_match_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_blue_match_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category = relationship("Category", back_populates="matches")
    area = relationship("Area", foreign_keys=[area_id], back_populates="queued_matches")
    red_cp = relationship("CategoryParticipant", foreign_keys=[red_cp_id])
    blue_cp = relationship("CategoryParticipant", foreign_keys=[blue_cp_id])
    winner_cp = relationship("CategoryParticipant", foreign_keys=[winner_cp_id])
    next_match = relationship("Match", remote_side=[id], foreign_keys=[next_match_id])

    events = relationship("MatchEvent", back_populates="match", cascade="all, delete-orphan")


class MatchEvent(Base):
    __tablename__ = "match_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    side: Mapped[str] = mapped_column(String(8), default="")
    value: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    match = relationship("Match", back_populates="events")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=True, index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(80))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
