"""Причины обоюдных поражений (без победителя и без очков за ничью)."""

from __future__ import annotations

DOUBLE_LOSS_REASONS = frozenset({
    "DOUBLE_FORFEIT",             # Обоюдное поражение (общий/смешанный случай)
    "DOUBLE_TECHNICAL_LOSS",      # Обоюдное техническое поражение
    "DOUBLE_WARNING_FORFEIT",     # Обоюдное поражение по предупреждениям
    "DOUBLE_DISQUALIFICATION",    # Обоюдная дисквалификация
    "DOUBLE_WITHDRAWAL",          # Обоюдное выбытие
})


def double_loss_reason(penalties: dict[str, str]) -> str:
    """Возвращает наиболее точную причину при двух назначенных санкциях."""
    if set(penalties) != {"red", "blue"}:
        raise ValueError("Для обоюдного поражения нужны санкции обеим сторонам")
    kind = penalties["red"] if penalties["red"] == penalties["blue"] else ""
    return {
        "TECHNICAL_LOSS": "DOUBLE_TECHNICAL_LOSS",
        "WARNING_FORFEIT": "DOUBLE_WARNING_FORFEIT",
        "DISQUALIFICATION": "DOUBLE_DISQUALIFICATION",
        "WITHDRAWAL": "DOUBLE_WITHDRAWAL",
    }.get(kind, "DOUBLE_FORFEIT")
