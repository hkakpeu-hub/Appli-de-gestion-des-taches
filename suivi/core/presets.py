"""Vues prédéfinies (filtres nommés) utilisées par les menus, le tableau de bord et l'assistant."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from .planning import week_start
from .tasks import TaskFilter

PRESET_LABELS = {
    "all": "Toutes les tâches",
    "today": "Mes tâches du jour",
    "week": "Mes tâches de la semaine",
    "overdue": "Mes tâches en retard",
    "upcoming": "Mes prochaines échéances",
    "blocked": "Mes tâches bloquées",
    "no_deadline": "Mes tâches sans date limite",
    "recent": "Mes tâches récemment modifiées",
    "done": "Mes tâches terminées",
    "active": "Tâches ouvertes",
    "todo": "Tâches à faire",
    "in_progress": "Tâches en cours",
    "due_today": "Échéances d'aujourd'hui",
    "late_start": "Début dépassé, non démarrées",
    "stale": "Sans mise à jour récente",
}
# vues proposées dans le sélecteur de la page « Toutes les tâches »
MENU_PRESETS = ["all", "today", "week", "overdue", "upcoming", "blocked", "no_deadline", "recent", "done",
                "active", "late_start", "stale"]


def make_filter(key: str, now: datetime, settings: dict, project_id: Optional[int] = None) -> TaskFilter:
    today = now.date()
    f = TaskFilter()
    if key == "today":
        f.today_view = True
    elif key == "week":
        ws = week_start(today)
        f.involving = (ws, ws + timedelta(days=6))
        f.only_active = True
    elif key == "overdue":
        f.delay = "any"
        f.sort = "deadline"
    elif key == "upcoming":
        f.only_active = True
        f.date_from = today
        f.date_to = today + timedelta(days=int(settings["upcoming_days"]))
    elif key == "blocked":
        f.kinds = ["blocked"]
    elif key == "no_deadline":
        f.no_deadline = True
        f.only_active = True
    elif key == "recent":
        f.updated_after = now - timedelta(days=7)
        f.sort, f.descending = "updated", True
    elif key == "done":
        f.kinds = ["done"]
        f.sort, f.descending = "updated", True
    elif key == "active":
        f.only_active = True
    elif key == "todo":
        f.kinds = ["todo"]
    elif key == "in_progress":
        f.kinds = ["in_progress"]
    elif key == "due_today":
        f.only_active = True
        f.date_from = f.date_to = today
    elif key == "late_start":
        f.kinds = ["todo"]
        f.date_field = "start_date"
        f.date_to = today - timedelta(days=1)
        f.sort = "start"
    elif key == "stale":
        f.only_active = True
        f.updated_before = now - timedelta(days=int(settings["stale_days"]))
        f.sort = "updated"
    if project_id:
        f.project_ids = [project_id]
    return f
