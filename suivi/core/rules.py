"""Règles métier pures (sans base de données ni interface), toutes paramétrées par la date/heure
courante afin d'être testables.

Principes :
 - une tâche Terminée ou Annulée n'est JAMAIS en retard (retards opérationnels) ;
 - une deadline « aujourd'hui » n'est pas un retard ; le retard commence le lendemain ;
 - les tâches supprimées (corbeille) sont ignorées partout.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from .models import KIND_BLOCKED, KIND_IN_PROGRESS, KIND_TODO, KIND_WAITING, Task

DELAY_LEVELS = {
    "none": "Pas en retard",
    "any": "En retard (tous)",
    "light": "Retard léger (1 à 3 j)",
    "moderate": "Retard modéré (4 à 14 j)",
    "severe": "Retard important (> 14 j)",
}


def overdue_days(t: Task, today: date) -> int:
    """Nombre de jours de retard (0 si pas en retard)."""
    if not t.is_active or t.deadline is None:
        return 0
    return max(0, (today - t.deadline).days)


def is_overdue(t: Task, today: date) -> bool:
    return overdue_days(t, today) > 0


def is_due_today(t: Task, today: date) -> bool:
    return t.is_active and t.deadline == today


def days_left(t: Task, today: date) -> Optional[int]:
    return None if t.deadline is None else (t.deadline - today).days


def is_due_soon(t: Task, today: date, within_days: int) -> bool:
    """Échéance dans les ``within_days`` prochains jours (aujourd'hui exclu, retard exclu)."""
    if not t.is_active or t.deadline is None:
        return False
    return 0 < (t.deadline - today).days <= within_days


def is_late_start(t: Task, today: date) -> bool:
    """La date de début est dépassée mais la tâche n'est pas démarrée (statut « À faire »)."""
    return t.is_active and t.status_kind == KIND_TODO and t.start_date is not None and t.start_date < today


def has_no_deadline(t: Task) -> bool:
    return t.is_active and t.deadline is None


def is_stale(t: Task, now: datetime, stale_days: int) -> bool:
    return t.is_active and (now - t.updated_at) >= timedelta(days=stale_days)


def is_stuck(t: Task, now: datetime, blocked_days: int, waiting_days: int) -> bool:
    """Bloquée / en attente depuis plus longtemps que le seuil configuré."""
    if not t.is_active:
        return False
    age = now - t.status_changed_at
    if t.status_kind == KIND_BLOCKED:
        return age >= timedelta(days=blocked_days)
    if t.status_kind == KIND_WAITING:
        return age >= timedelta(days=waiting_days)
    return False


def delay_level(t: Task, today: date) -> str:
    d = overdue_days(t, today)
    if d == 0:
        return "none"
    if d <= 3:
        return "light"
    if d <= 14:
        return "moderate"
    return "severe"


def matches_delay(t: Task, today: date, wanted: Optional[str]) -> bool:
    if not wanted:
        return True
    lvl = delay_level(t, today)
    if wanted == "none":
        return lvl == "none"
    if wanted == "any":
        return lvl != "none"
    return lvl == wanted


def planned_interval(t: Task) -> Optional[tuple[datetime, datetime]]:
    """Créneau planifié (début, fin) si la tâche a une date de début ET une heure de début.

    Sans heure de fin : durée estimée si connue, sinon 1 h. Retourne None si non planifiée.
    """
    if t.start_date is None or t.start_time is None:
        return None
    start = datetime.combine(t.start_date, t.start_time)
    if t.end_time is not None:
        end = datetime.combine(t.start_date, t.end_time)
        if end <= start:
            end = start + timedelta(minutes=30)
    else:
        end = start + timedelta(minutes=t.est_minutes or 60)
    return start, end


def is_in_progress_like(t: Task) -> bool:
    return t.status_kind in (KIND_IN_PROGRESS, KIND_WAITING, KIND_BLOCKED)


def urgency_score(t: Task, today: date) -> float:
    """Score servant à classer « les tâches les plus urgentes » (plus grand = plus urgent)."""
    if not t.is_active:
        return -1.0
    prio = {"critical": 40, "high": 20, "normal": 8, "low": 0}.get(t.priority, 8)
    if t.deadline is None:
        base = 0.0
    else:
        left = (t.deadline - today).days
        base = 100 + min(60, -left * 4) if left < 0 else max(0.0, 60 - left * 5)
    if t.status_kind == KIND_BLOCKED:
        base += 5
    return base + prio
