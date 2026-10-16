"""Modèles de données (dataclasses) et constantes métier."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional

# Natures de statut : les règles métier se basent sur la nature, jamais sur le libellé
# (les libellés sont configurables par l'utilisateur).
KIND_TODO = "todo"
KIND_IN_PROGRESS = "in_progress"
KIND_WAITING = "waiting"
KIND_BLOCKED = "blocked"
KIND_DONE = "done"
KIND_CANCELLED = "cancelled"
KINDS = {
    KIND_TODO: "À faire",
    KIND_IN_PROGRESS: "En cours",
    KIND_WAITING: "En attente",
    KIND_BLOCKED: "Bloquée",
    KIND_DONE: "Terminée",
    KIND_CANCELLED: "Annulée",
}
CLOSED_KINDS = (KIND_DONE, KIND_CANCELLED)

PRIORITIES = ["low", "normal", "high", "critical"]
PRIORITY_LABELS = {"low": "Faible", "normal": "Normal", "high": "Élevé", "critical": "Critique"}
PRIORITY_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}
PRIORITY_COLORS = {"low": "#94A3B8", "normal": "#3B82F6", "high": "#F59E0B", "critical": "#DC2626"}

DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"


def to_date(value) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], DATE_FMT).date()


def to_datetime(value) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time())
    s = str(value)
    return datetime.strptime(s[:19], DATETIME_FMT) if "T" in s else datetime.strptime(s[:10], DATE_FMT)


def to_time(value) -> Optional[time]:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    return datetime.strptime(str(value)[:5], "%H:%M").time()


def iso_date(value) -> Optional[str]:
    d = to_date(value)
    return d.strftime(DATE_FMT) if d else None


def iso_datetime(value) -> Optional[str]:
    d = to_datetime(value)
    return d.strftime(DATETIME_FMT) if d else None


def iso_time(value) -> Optional[str]:
    t = to_time(value)
    return t.strftime("%H:%M") if t else None


@dataclass
class Status:
    id: int
    label: str
    kind: str
    color: str
    position: int
    is_active: bool = True


@dataclass
class Space:
    id: int
    name: str
    icon: str = "✔"
    color: str = "#2563EB"
    kind: str = "tasks"
    position: int = 0
    enabled: bool = True


@dataclass
class Attachment:
    id: int
    task_id: int
    display_name: str
    path: str
    is_relative: bool
    size: Optional[int]
    created_at: datetime


@dataclass
class Recurrence:
    id: int
    space_id: int
    title: str
    project_id: Optional[int]
    project_name: str
    description: str
    assignee: str
    priority: str
    start_time: Optional[time]
    end_time: Optional[time]
    est_minutes: Optional[int]
    freq: str
    interval: int
    weekdays: list
    month_day: Optional[int]
    start_date: Optional[date]
    end_date: Optional[date]
    count: Optional[int]
    auto_close: bool
    active: bool


@dataclass
class Project:
    id: int
    space_id: int
    name: str
    color: Optional[str] = None
    description: Optional[str] = None
    archived: bool = False


@dataclass
class Task:
    id: int
    title: str
    project_id: Optional[int]
    project_name: str
    description: str
    assignee: str
    created_at: datetime
    start_date: Optional[date]
    deadline: Optional[date]
    status_id: int
    status_label: str
    status_kind: str
    status_color: str
    priority: str
    completed_at: Optional[datetime]
    start_time: Optional[time]
    end_time: Optional[time]
    est_minutes: Optional[int]
    actual_minutes: Optional[int]
    extra_date: Optional[date]
    source: str
    updated_at: datetime
    status_changed_at: datetime
    deleted_at: Optional[datetime] = None
    project_color: Optional[str] = None
    space_id: int = 1
    n_attach: int = 0
    series_id: Optional[int] = None

    @property
    def is_closed(self) -> bool:
        return self.status_kind in CLOSED_KINDS

    @property
    def is_active(self) -> bool:
        return not self.is_closed and self.deleted_at is None

    @property
    def priority_label(self) -> str:
        return PRIORITY_LABELS.get(self.priority, self.priority)

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Task":
        return cls(
            id=r["id"],
            title=r["title"],
            project_id=r["project_id"],
            project_name=r["project_name"] or "",
            description=r["description"] or "",
            assignee=r["assignee"] or "",
            created_at=to_datetime(r["created_at"]),
            start_date=to_date(r["start_date"]),
            deadline=to_date(r["deadline"]),
            status_id=r["status_id"],
            status_label=r["status_label"],
            status_kind=r["status_kind"],
            status_color=r["status_color"],
            priority=r["priority"],
            completed_at=to_datetime(r["completed_at"]),
            start_time=to_time(r["start_time"]),
            end_time=to_time(r["end_time"]),
            est_minutes=r["est_minutes"],
            actual_minutes=r["actual_minutes"],
            extra_date=to_date(r["extra_date"]),
            source=r["source"] or "",
            updated_at=to_datetime(r["updated_at"]),
            status_changed_at=to_datetime(r["status_changed_at"]),
            deleted_at=to_datetime(r["deleted_at"]),
            project_color=r["project_color"],
            space_id=r["space_id"],
            n_attach=r["n_attach"],
            series_id=r["series_id"],
        )


@dataclass
class Alert:
    id: int
    task_id: int
    kind: str
    level: str
    title: str
    message: str
    created_at: datetime
    read_at: Optional[datetime]
    snoozed_until: Optional[datetime]
    notified_at: Optional[datetime]
    task_title: str = ""
    project_name: str = ""
    deadline: Optional[date] = None
    status_label: str = ""
    space_id: int = 1
    space_name: str = ""


@dataclass
class HistoryEvent:
    id: int
    task_id: Optional[int]
    task_title: str
    event: str
    field: str
    old_value: str
    new_value: str
    at: datetime


@dataclass
class Comment:
    id: int
    task_id: int
    body: str
    created_at: datetime


@dataclass
class TaskInput:
    """Données saisies pour créer/modifier une tâche (None = non renseigné)."""

    title: str = ""
    project_name: str = ""
    description: str = ""
    assignee: str = ""
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    status_id: Optional[int] = None
    priority: str = "normal"
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    est_minutes: Optional[int] = None
    actual_minutes: Optional[int] = None
    extra_date: Optional[date] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    source: str = ""
    comments: list[str] = field(default_factory=list)
    space_id: Optional[int] = None  # None = espace courant
    series_id: Optional[int] = None  # série de répétition
    occurrence_date: Optional[date] = None


class ValidationError(ValueError):
    """Erreur de saisie lisible par l'utilisateur (message en français)."""
