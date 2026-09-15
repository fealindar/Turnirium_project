"""Совместимый фасад предметной логики Turnirium.

Новая реализация разделена по модулям ``app.services``. Этот файл сохраняет
стабильные импорты для API, тестов и сторонних локальных сценариев.
"""

from .services.common import (
    add_category_participant, audit, category_dict, clear_category_matches,
    effective_remaining_ms, json_load, match_dict, now_utc,
)
from .services.scheduling import (
    assign_ready_category_unit, auto_assign_ready_matches, cross_area_repeat_warnings,
    optimize_area_queue, queue_repeat_warnings,
)
from .services.brackets import generate_knockout
from .services.groups import generate_groups, generate_round_robin, rebuild_groups_from_assignments, start_group_stage
from .services.standings import elimination_standings, standings
from .services.playoffs import generate_group_playoff, rebuild_bracket_stage_from_slots
from .services.swiss import generate_swiss_round, rebuild_swiss_round_from_slots, start_swiss_round, swiss_current_round
from .services.matches import (
    add_warning, apply_score, correct_finished_match, finish_match, restore_participant,
    undo_last_event, withdraw_participant,
)
from .services.maintenance import backup_database, clear_tournament_data

__all__ = [
    "add_category_participant", "add_warning", "apply_score", "assign_ready_category_unit", "audit",
    "auto_assign_ready_matches", "backup_database", "category_dict",
    "clear_category_matches", "clear_tournament_data", "correct_finished_match",
    "cross_area_repeat_warnings", "effective_remaining_ms", "elimination_standings", "finish_match",
    "generate_group_playoff", "generate_groups", "generate_knockout",
    "generate_round_robin", "generate_swiss_round", "json_load", "match_dict",
    "now_utc", "optimize_area_queue", "queue_repeat_warnings",
    "rebuild_bracket_stage_from_slots", "rebuild_groups_from_assignments",
    "rebuild_swiss_round_from_slots", "restore_participant", "standings",
    "start_group_stage", "start_swiss_round", "swiss_current_round",
    "undo_last_event", "withdraw_participant",
]
