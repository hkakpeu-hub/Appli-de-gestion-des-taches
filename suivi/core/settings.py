"""Paramètres de l'application (table ``settings``, valeurs JSON).

La clé API n'est JAMAIS stockée ici (voir ``suivi.ai.secrets``).
"""
from __future__ import annotations

import json
from typing import Any

from ..db import Database

DEFAULTS: dict[str, Any] = {
    # alertes
    "reminder_days": [7, 3, 1, 0],
    "start_reminder_minutes": 30,
    "end_warning_minutes": 15,
    "blocked_days": 3,
    "waiting_days": 5,
    "stale_days": 14,
    "upcoming_days": 7,
    "overdue_reemit_days": 1,
    "notstarted_reemit_days": 3,
    "stuck_reemit_days": 3,
    "alerts_enabled": True,
    "native_notifications": True,
    "max_toasts_per_check": 3,
    "check_interval_seconds": 60,
    # sauvegardes
    "backup_auto": True,
    "backup_keep": 10,
    "backup_interval_hours": 12,
    # planning
    "work_start_hour": 8,
    "work_end_hour": 19,
    "min_free_slot_minutes": 30,
    # interface
    "minimize_to_tray": True,
    "assignee_default": "",
    # IA (la clé est dans le coffre Windows, pas ici)
    "ai_enabled": False,
    "ai_model": "claude-sonnet-5-5",
}


class Settings:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> Any:
        row = self.db.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return DEFAULTS[key]
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return DEFAULTS[key]

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def all(self) -> dict[str, Any]:
        return {k: self.get(k) for k in DEFAULTS}
