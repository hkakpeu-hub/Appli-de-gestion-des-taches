"""Tâches répétitives (ex. « Culte, tous les dimanches de 7 h à 11 h »).

Principe : une *série* (table ``recurrences``) décrit la règle ; chaque occurrence est une **vraie tâche**
(liée à la série par ``series_id``) générée à l'avance sur un horizon glissant (90 jours). Ainsi les occurrences
apparaissent dans le planning, le tableau de bord et les alertes comme n'importe quelle tâche, et chacune peut
être terminée, déplacée ou supprimée individuellement. La génération est idempotente (une occurrence supprimée
n'est jamais recréée) et ne crée jamais d'occurrences dans le passé.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterator, Optional

from ..db import Database
from .models import (
    KIND_DONE, Recurrence, TaskInput, ValidationError, iso_date, iso_datetime, iso_time, to_date, to_time,
)
from .projects import ProjectService
from .spaces import CURRENT, Scope
from .statuses import StatusService
from .tasks import TaskService

log = logging.getLogger(__name__)
HORIZON_DAYS = 90
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FREQ_LABELS = {"daily": "Tous les jours", "weekly": "Toutes les semaines", "monthly": "Tous les mois"}


@dataclass
class RecurrenceInput:
    title: str = ""
    project_name: str = ""
    description: str = ""
    assignee: str = ""
    priority: str = "normal"
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    est_minutes: Optional[int] = None
    freq: str = "weekly"
    interval: int = 1
    weekdays: list[int] = field(default_factory=list)  # 0 = lundi … 6 = dimanche
    month_day: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    count: Optional[int] = None
    auto_close: bool = False


def occurrences(r: Recurrence | RecurrenceInput, frm: date, to: date) -> Iterator[date]:
    """Dates d'occurrence de la règle comprises entre ``frm`` et ``to`` (incluses), dans l'ordre."""
    start = r.start_date
    if start is None:
        return
    last = min(to, r.end_date) if r.end_date else to
    n = 0  # nombre d'occurrences depuis le début (pour la limite « après N occurrences »)
    d = start
    interval = max(1, r.interval)
    monday0 = start - timedelta(days=start.weekday())
    while d <= last:
        hit = False
        if r.freq == "daily":
            hit = (d - start).days % interval == 0
        elif r.freq == "weekly":
            days = r.weekdays or [start.weekday()]
            hit = d.weekday() in days and ((d - monday0).days // 7) % interval == 0
        elif r.freq == "monthly":
            months = (d.year - start.year) * 12 + d.month - start.month
            want = r.month_day or start.day
            hit = months >= 0 and months % interval == 0 and d.day == min(want, calendar.monthrange(d.year, d.month)[1])
        if hit:
            n += 1
            if r.count and n > r.count:
                return
            if d >= frm:
                yield d
        d += timedelta(days=1)


def describe(r: Recurrence | RecurrenceInput) -> str:
    """Résumé lisible : « Toutes les semaines le dimanche, de 07:00 à 11:00 »."""
    every = max(1, r.interval)
    if r.freq == "daily":
        txt = "Tous les jours" if every == 1 else f"Tous les {every} jours"
    elif r.freq == "weekly":
        days = " et ".join(WEEKDAYS[d] for d in sorted(r.weekdays or [r.start_date.weekday() if r.start_date else 0]))
        txt = (f"Toutes les semaines le {days}" if every == 1 else f"Toutes les {every} semaines le {days}")
    else:
        day = r.month_day or (r.start_date.day if r.start_date else 1)
        txt = f"Le {day} de chaque mois" if every == 1 else f"Le {day}, tous les {every} mois"
    if r.start_time:
        txt += f", de {r.start_time:%H:%M}" + (f" à {r.end_time:%H:%M}" if r.end_time else "")
    if r.end_date:
        txt += f", jusqu'au {r.end_date:%d/%m/%Y}"
    elif r.count:
        txt += f", {r.count} fois"
    return txt


class RecurrenceService:
    def __init__(self, db: Database, tasks: TaskService, projects: ProjectService, statuses: StatusService,
                 scope: Scope, clock: Callable[[], datetime] = datetime.now):
        self.db, self.tasks, self.projects, self.statuses, self.scope, self.clock = db, tasks, projects, statuses, scope, clock

    # ------------------------------------------------------------------ lecture
    @staticmethod
    def _row(r) -> Recurrence:
        return Recurrence(
            id=r["id"], space_id=r["space_id"], title=r["title"], project_id=r["project_id"], project_name=r["project_name"] or "",
            description=r["description"] or "", assignee=r["assignee"] or "", priority=r["priority"],
            start_time=to_time(r["start_time"]), end_time=to_time(r["end_time"]), est_minutes=r["est_minutes"],
            freq=r["freq"], interval=r["interval"], weekdays=[int(x) for x in (r["weekdays"] or "").split(",") if x != ""],
            month_day=r["month_day"], start_date=to_date(r["start_date"]), end_date=to_date(r["end_date"]), count=r["count"],
            auto_close=bool(r["auto_close"]), active=bool(r["active"]),
        )

    _SELECT = ("SELECT s.*, p.name AS project_name FROM recurrences s LEFT JOIN projects p ON p.id=s.project_id")

    def list(self, space_id=CURRENT, include_inactive: bool = False) -> list[Recurrence]:
        where, params = [], []
        sp = self.scope.resolve(space_id)
        if sp is not None:
            where.append("s.space_id=?"); params.append(sp)
        if not include_inactive:
            where.append("s.active=1")
        sql = self._SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY s.title COLLATE NOCASE"
        return [self._row(r) for r in self.db.conn.execute(sql, params)]

    def get(self, series_id: int) -> Recurrence:
        r = self.db.conn.execute(self._SELECT + " WHERE s.id=?", (series_id,)).fetchone()
        if r is None:
            raise ValidationError("Série introuvable.")
        return self._row(r)

    def next_dates(self, r: Recurrence | RecurrenceInput, n: int = 5, frm: Optional[date] = None) -> list[date]:
        frm = max(frm or self.clock().date(), r.start_date or date.min)
        out = []
        for d in occurrences(r, frm, frm + timedelta(days=366 * 3)):
            out.append(d)
            if len(out) >= n:
                break
        return out

    # ------------------------------------------------------------------ validation
    def validate(self, d: RecurrenceInput) -> None:
        if not (d.title or "").strip():
            raise ValidationError("L'intitulé de la tâche répétitive est obligatoire.")
        if d.freq not in FREQ_LABELS:
            raise ValidationError("Fréquence invalide.")
        if d.interval < 1 or d.interval > 365:
            raise ValidationError("L'intervalle doit être compris entre 1 et 365.")
        if d.start_date is None:
            raise ValidationError("Indiquez la date de la première occurrence.")
        if d.freq == "weekly" and not d.weekdays:
            raise ValidationError("Choisissez au moins un jour de la semaine.")
        if d.freq == "monthly" and d.month_day is not None and not 1 <= d.month_day <= 31:
            raise ValidationError("Le jour du mois doit être compris entre 1 et 31.")
        if d.end_time and not d.start_time:
            raise ValidationError("Renseignez l'heure de début avant l'heure de fin.")
        if d.start_time and d.end_time and d.end_time <= d.start_time:
            raise ValidationError("L'heure de fin doit être postérieure à l'heure de début.")
        if d.end_date and d.end_date < d.start_date:
            raise ValidationError("La date de fin de la série est antérieure à son début.")
        if d.count is not None and d.count < 1:
            raise ValidationError("Le nombre d'occurrences doit être d'au moins 1.")
        if not next(occurrences(d, d.start_date, d.start_date + timedelta(days=366 * 3)), None):
            raise ValidationError("Cette règle ne produit aucune occurrence.")

    # ------------------------------------------------------------------ écriture
    def create(self, d: RecurrenceInput, space_id=CURRENT) -> Recurrence:
        self.validate(d)
        sp = self.scope.resolve(space_id) or self.scope.space_id or 1
        project = self.projects.get_or_create(d.project_name, sp)
        if project and project.archived:
            raise ValidationError(f"Le projet « {project.name} » est archivé.")
        with self.db.transaction() as c:
            cur = c.execute(
                """INSERT INTO recurrences(space_id,title,project_id,description,assignee,priority,start_time,end_time,est_minutes,
                   freq,interval,weekdays,month_day,start_date,end_date,count,auto_close,active,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (sp, d.title.strip(), project.id if project else None, (d.description or "").strip(), (d.assignee or "").strip(),
                 d.priority, iso_time(d.start_time), iso_time(d.end_time), d.est_minutes, d.freq, d.interval,
                 ",".join(str(x) for x in sorted(d.weekdays)), d.month_day, iso_date(d.start_date), iso_date(d.end_date),
                 d.count, 1 if d.auto_close else 0, iso_datetime(self.clock())))
            series_id = cur.lastrowid
        self.sync()
        return self.get(series_id)

    def update(self, series_id: int, d: RecurrenceInput) -> Recurrence:
        """Modifie la règle. Les occurrences futures encore intactes sont régénérées ; les autres sont conservées."""
        self.validate(d)
        old = self.get(series_id)
        project = self.projects.get_or_create(d.project_name, old.space_id)
        today = self.clock().date()
        with self.db.transaction() as c:
            c.execute(
                """UPDATE recurrences SET title=?,project_id=?,description=?,assignee=?,priority=?,start_time=?,end_time=?,
                   est_minutes=?,freq=?,interval=?,weekdays=?,month_day=?,start_date=?,end_date=?,count=?,auto_close=?,
                   generated_until=NULL WHERE id=?""",
                (d.title.strip(), project.id if project else None, (d.description or "").strip(), (d.assignee or "").strip(),
                 d.priority, iso_time(d.start_time), iso_time(d.end_time), d.est_minutes, d.freq, d.interval,
                 ",".join(str(x) for x in sorted(d.weekdays)), d.month_day, iso_date(d.start_date), iso_date(d.end_date),
                 d.count, 1 if d.auto_close else 0, series_id))
            self._drop_untouched_future(c, series_id, today)
        self.sync()
        return self.get(series_id)

    def _drop_untouched_future(self, c, series_id: int, today: date) -> int:
        """Supprime les occurrences futures « à faire » sans commentaire ni pièce jointe (elles seront régénérées)."""
        rows = c.execute(
            """SELECT t.id FROM tasks t JOIN statuses s ON s.id=t.status_id WHERE t.series_id=? AND t.occurrence_date>=?
               AND s.kind='todo' AND t.deleted_at IS NULL
               AND NOT EXISTS (SELECT 1 FROM comments m WHERE m.task_id=t.id)
               AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.task_id=t.id)""", (series_id, iso_date(today))).fetchall()
        for r in rows:
            c.execute("DELETE FROM tasks WHERE id=?", (r["id"],))
        return len(rows)

    def stop(self, series_id: int) -> int:
        """Arrête la série : les occurrences futures intactes sont supprimées, l'historique passé est conservé."""
        today = self.clock().date()
        with self.db.transaction() as c:
            c.execute("UPDATE recurrences SET active=0 WHERE id=?", (series_id,))
            n = self._drop_untouched_future(c, series_id, today)
        self.tasks.notify_changed()
        return n

    def delete(self, series_id: int) -> None:
        """Supprime la série et ses occurrences intactes ; les occurrences traitées restent comme tâches ordinaires."""
        self.stop(series_id)
        with self.db.transaction() as c:
            c.execute("UPDATE tasks SET series_id=NULL WHERE series_id=?", (series_id,))
            c.execute("DELETE FROM recurrences WHERE id=?", (series_id,))
        self.tasks.notify_changed()

    # ------------------------------------------------------------------ génération
    def sync(self, now: Optional[datetime] = None) -> int:
        """Génère les occurrences manquantes (jusqu'à 90 jours) et clôture les occurrences passées des séries
        « événement ». Retourne le nombre de changements."""
        now = now or self.clock()
        today = now.date()
        horizon = today + timedelta(days=HORIZON_DAYS)
        changed = 0
        for s in self.list(space_id=None):
            sp_project = self.projects.get(s.project_id).name if s.project_id else ""
            existing = {r["occurrence_date"] for r in self.db.conn.execute(
                "SELECT occurrence_date FROM tasks WHERE series_id=?", (s.id,))}
            with self.tasks.batch():
                for d in occurrences(s, max(today, s.start_date), horizon):
                    if iso_date(d) in existing:
                        continue
                    try:
                        self.tasks.create(TaskInput(
                            title=s.title, project_name=sp_project, description=s.description, assignee=s.assignee,
                            priority=s.priority, start_date=d, deadline=d, start_time=s.start_time, end_time=s.end_time,
                            est_minutes=s.est_minutes, space_id=s.space_id, source="Répétition", series_id=s.id,
                            occurrence_date=d), history=False)
                    except ValidationError as exc:  # ex. projet archivé : on saute cette série
                        log.warning("Série %s ignorée : %s", s.id, exc)
                        break
                    changed += 1
            if s.auto_close:
                changed += self._auto_close(s, now)
        return changed

    def _auto_close(self, s: Recurrence, now: datetime) -> int:
        """Occurrences passées (ou terminées aujourd'hui) d'une série « événement » : marquées terminées."""
        done_id = self.statuses.first_of_kind(KIND_DONE).id
        n = 0
        for t in self.tasks.all(space_id=None, include_archived=True):
            if t.series_id != s.id or not t.is_active:
                continue
            over = t.start_date < now.date() or (t.start_date == now.date() and t.end_time is not None and t.end_time <= now.time())
            if over:
                self.tasks.update(t.id, self.tasks.to_input(t, status_id=done_id), strict=False)
                n += 1
        return n
