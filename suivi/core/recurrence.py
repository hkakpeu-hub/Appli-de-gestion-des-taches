"""Répétitions : tâches répétitives *et* événements récurrents (ex. « Culte, tous les dimanches de 7 h à 11 h »).

Une *série* (table ``recurrences``, ``kind`` = ``task`` ou ``event``) décrit la règle ; les occurrences sont
générées à l'avance sur un horizon glissant de 90 jours, sans jamais créer d'occurrence dans le passé :
 - série de **tâches** : chaque occurrence est une vraie tâche (``tasks.series_id``), créée ``task_weeks`` semaine(s)
   (1 par défaut) avant sa date pour ne pas encombrer les listes ;
 - série d'**événements** : chaque occurrence est un événement (``events.series_id``), jamais compté comme tâche.
   Une série d'événements peut porter des **tâches modèles** (« Chanter », « Danser »…) recréées et rattachées à
   chaque occurrence, avec une échéance « N jours avant ».
La génération est idempotente : une occurrence supprimée n'est jamais recréée.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterator, Optional

from ..db import Database
from .events import EventInput, EventService
from .models import (
    EventTemplate, Recurrence, TaskInput, ValidationError, iso_date, iso_datetime, iso_time, to_date, to_time,
)
from .projects import ProjectService
from .spaces import CURRENT, Scope
from .statuses import StatusService
from .tasks import TaskService

log = logging.getLogger(__name__)
HORIZON_DAYS = 90  # occurrences (tâches ou événements) générées à l'avance
DEFAULT_TASK_WEEKS = 1  # tâches modèles d'un événement : créées 1 semaine avant la date (réglable par série)
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
    kind: str = "task"  # task | event
    location: str = ""
    templates: list[EventTemplate] = field(default_factory=list)  # événements : tâches modèles
    task_weeks: int = DEFAULT_TASK_WEEKS  # événements : créer les tâches N semaine(s) à l'avance


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
                 scope: Scope, clock: Callable[[], datetime] = datetime.now, events: Optional[EventService] = None):
        self.db, self.tasks, self.projects, self.statuses, self.scope, self.clock = db, tasks, projects, statuses, scope, clock
        self.events = events or EventService(db, tasks, statuses, scope, clock)

    # ------------------------------------------------------------------ lecture
    @staticmethod
    def _row(r) -> Recurrence:
        return Recurrence(
            id=r["id"], space_id=r["space_id"], title=r["title"], project_id=r["project_id"], project_name=r["project_name"] or "",
            description=r["description"] or "", assignee=r["assignee"] or "", priority=r["priority"],
            start_time=to_time(r["start_time"]), end_time=to_time(r["end_time"]), est_minutes=r["est_minutes"],
            freq=r["freq"], interval=r["interval"], weekdays=[int(x) for x in (r["weekdays"] or "").split(",") if x != ""],
            month_day=r["month_day"], start_date=to_date(r["start_date"]), end_date=to_date(r["end_date"]), count=r["count"],
            auto_close=bool(r["auto_close"]), active=bool(r["active"]), kind=r["kind"], location=r["location"] or "",
            task_weeks=r["task_weeks"],
        )

    _SELECT = ("SELECT s.*, p.name AS project_name FROM recurrences s LEFT JOIN projects p ON p.id=s.project_id")

    def list(self, space_id=CURRENT, include_inactive: bool = False, kind: Optional[str] = None) -> list[Recurrence]:
        where, params = [], []
        sp = self.scope.resolve(space_id)
        if sp is not None:
            where.append("s.space_id=?"); params.append(sp)
        if not include_inactive:
            where.append("s.active=1")
        if kind:
            where.append("s.kind=?"); params.append(kind)
        sql = self._SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY s.title COLLATE NOCASE"
        return [self._row(r) for r in self.db.conn.execute(sql, params)]

    def get(self, series_id: int) -> Recurrence:
        r = self.db.conn.execute(self._SELECT + " WHERE s.id=?", (series_id,)).fetchone()
        if r is None:
            raise ValidationError("Série introuvable.")
        return self._row(r)

    def templates(self, series_id: int) -> list[EventTemplate]:
        rows = self.db.conn.execute("SELECT * FROM event_templates WHERE series_id=? ORDER BY position, id", (series_id,))
        return [EventTemplate(r["title"], r["assignee"] or "", r["days_before"], r["id"]) for r in rows]

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
            raise ValidationError("L'intitulé est obligatoire.")
        if d.kind not in ("task", "event"):
            raise ValidationError("Type de répétition invalide.")
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
        if d.task_weeks < 1 or d.task_weeks > 26:
            raise ValidationError("Les tâches doivent être créées 1 à 26 semaines à l'avance.")
        for t in d.templates:
            if not (t.title or "").strip():
                raise ValidationError("Une tâche modèle n'a pas d'intitulé.")
            if t.days_before < 0 or t.days_before > 365:
                raise ValidationError("« Jours avant » doit être compris entre 0 et 365.")

    # ------------------------------------------------------------------ écriture
    def create(self, d: RecurrenceInput, space_id=CURRENT) -> Recurrence:
        self.validate(d)
        sp = self.scope.resolve(space_id) or self.scope.space_id or 1
        project = None if d.kind == "event" else self.projects.get_or_create(d.project_name, sp)
        if project and project.archived:
            raise ValidationError(f"Le projet « {project.name} » est archivé.")
        with self.db.transaction() as c:
            cur = c.execute(
                """INSERT INTO recurrences(space_id,title,project_id,description,assignee,priority,start_time,end_time,est_minutes,
                   freq,interval,weekdays,month_day,start_date,end_date,count,auto_close,active,created_at,kind,location,task_weeks)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,1,?,?,?,?)""",
                (sp, d.title.strip(), project.id if project else None, (d.description or "").strip(), (d.assignee or "").strip(),
                 d.priority, iso_time(d.start_time), iso_time(d.end_time), d.est_minutes, d.freq, d.interval,
                 ",".join(str(x) for x in sorted(d.weekdays)), d.month_day, iso_date(d.start_date), iso_date(d.end_date),
                 d.count, iso_datetime(self.clock()), d.kind, (d.location or "").strip(), d.task_weeks))
            series_id = cur.lastrowid
            for pos, t in enumerate(d.templates):
                c.execute("INSERT INTO event_templates(series_id,title,assignee,days_before,position) VALUES (?,?,?,?,?)",
                          (series_id, t.title.strip(), (t.assignee or "").strip(), t.days_before, pos))
        self.sync()
        return self.get(series_id)

    def update(self, series_id: int, d: RecurrenceInput) -> Recurrence:
        """Modifie la règle. Les occurrences futures intactes sont adaptées ou régénérées ; celles qui ont été
        traitées (tâche faite, commentaire, pièce jointe…) sont conservées telles quelles."""
        d.kind = self.get(series_id).kind  # le type d'une série ne change pas
        self.validate(d)
        old = self.get(series_id)
        old_templates = self.templates(series_id)
        project = None if d.kind == "event" else self.projects.get_or_create(d.project_name, old.space_id)
        today = self.clock().date()
        with self.db.transaction() as c:
            c.execute(
                """UPDATE recurrences SET title=?,project_id=?,description=?,assignee=?,priority=?,start_time=?,end_time=?,
                   est_minutes=?,freq=?,interval=?,weekdays=?,month_day=?,start_date=?,end_date=?,count=?,location=?,task_weeks=?,
                   generated_until=NULL WHERE id=?""",
                (d.title.strip(), project.id if project else None, (d.description or "").strip(), (d.assignee or "").strip(),
                 d.priority, iso_time(d.start_time), iso_time(d.end_time), d.est_minutes, d.freq, d.interval,
                 ",".join(str(x) for x in sorted(d.weekdays)), d.month_day, iso_date(d.start_date), iso_date(d.end_date),
                 d.count, (d.location or "").strip(), d.task_weeks, series_id))
            if d.kind == "task":
                self._drop_untouched_future(c, series_id, today)
            else:
                self._update_templates(c, series_id, d.templates)
        if d.kind == "event":
            self._refit_events(series_id, today)
            self._refit_template_tasks(series_id, old_templates, today)
        self.sync()
        return self.get(series_id)

    # -- tâches ---------------------------------------------------------------
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

    # -- événements -------------------------------------------------------------
    def _update_templates(self, c, series_id: int, templates: list[EventTemplate]) -> None:
        keep = {t.id for t in templates if t.id}
        for r in c.execute("SELECT id FROM event_templates WHERE series_id=?", (series_id,)).fetchall():
            if r["id"] not in keep:
                c.execute("DELETE FROM event_templates WHERE id=?", (r["id"],))
        for pos, t in enumerate(templates):
            if t.id:
                c.execute("UPDATE event_templates SET title=?,assignee=?,days_before=?,position=? WHERE id=?",
                          (t.title.strip(), (t.assignee or "").strip(), t.days_before, pos, t.id))
            else:
                c.execute("INSERT INTO event_templates(series_id,title,assignee,days_before,position) VALUES (?,?,?,?,?)",
                          (series_id, t.title.strip(), (t.assignee or "").strip(), t.days_before, pos))

    def _future_events(self, series_id: int, today: date):
        return [e for e in self.events.list(frm=today, space_id=None) if e.series_id == series_id]

    def _refit_events(self, series_id: int, today: date) -> None:
        """Aligne les événements futurs sur la nouvelle règle : mise à jour en place, retrait des dates devenues
        inutiles (si intactes), les dates manquantes sont créées par ``sync``."""
        s = self.get(series_id)
        want = set(occurrences(s, max(today, s.start_date), today + timedelta(days=HORIZON_DAYS)))
        for e in self._future_events(series_id, today):
            if e.date in want:
                self.events.update(e.id, EventInput(s.title, e.date, s.start_time, s.end_time, s.location, s.description))
            elif self.events.is_untouched(e.id):
                self.events.purge(e.id)

    def _refit_template_tasks(self, series_id: int, old: list[EventTemplate], today: date) -> None:
        """Répercute les changements de tâches modèles sur les tâches futures encore intactes."""
        new = {t.id: t for t in self.templates(series_id)}
        for e in self._future_events(series_id, today):
            for r in self.db.conn.execute(
                    """SELECT t.id, t.template_id FROM tasks t JOIN statuses s ON s.id=t.status_id
                       WHERE t.event_id=? AND t.template_id IS NOT NULL AND t.deleted_at IS NULL AND s.kind='todo'
                       AND NOT EXISTS (SELECT 1 FROM comments m WHERE m.task_id=t.id)
                       AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.task_id=t.id)""", (e.id,)).fetchall():
                tpl = new.get(r["template_id"])
                if tpl is None:  # modèle supprimé
                    self.db.conn.execute("DELETE FROM tasks WHERE id=?", (r["id"],))
                    continue
                due = e.date - timedelta(days=tpl.days_before)
                t = self.tasks.get(r["id"])
                self.tasks.update(t.id, self.tasks.to_input(t, title=tpl.title, assignee=tpl.assignee, start_date=due, deadline=due),
                                  strict=False)
        self.db.conn.commit()

    def stop(self, series_id: int) -> int:
        """Arrête la série : occurrences futures intactes supprimées, historique passé conservé. Retourne le nombre retiré."""
        s = self.get(series_id)
        today = self.clock().date()
        with self.db.transaction() as c:
            c.execute("UPDATE recurrences SET active=0 WHERE id=?", (series_id,))
            n = self._drop_untouched_future(c, series_id, today) if s.kind == "task" else 0
        if s.kind == "event":
            for e in self._future_events(series_id, today):
                if self.events.is_untouched(e.id):
                    self.events.purge(e.id)
                    n += 1
        self.tasks.notify_changed()
        return n

    def delete(self, series_id: int) -> None:
        """Supprime la série (occurrences intactes à venir comprises) ; ce qui a été traité reste, détaché de la série."""
        self.stop(series_id)
        with self.db.transaction() as c:
            c.execute("UPDATE tasks SET series_id=NULL WHERE series_id=?", (series_id,))
            c.execute("UPDATE events SET series_id=NULL WHERE series_id=?", (series_id,))
            c.execute("DELETE FROM recurrences WHERE id=?", (series_id,))
        self.tasks.notify_changed()

    # ------------------------------------------------------------------ génération
    def sync(self, now: Optional[datetime] = None) -> int:
        """Génère les occurrences manquantes (jusqu'à 90 jours). Retourne le nombre de créations."""
        now = now or self.clock()
        today = now.date()
        horizon = today + timedelta(days=HORIZON_DAYS)
        changed = 0
        for s in self.list(space_id=None):
            if s.kind == "event":
                changed += self._sync_events(s, today, horizon)
            else:
                changed += self._sync_tasks(s, today, horizon)
        return changed

    def _sync_tasks(self, s: Recurrence, today: date, horizon: date) -> int:
        changed = 0
        project = self.projects.get(s.project_id).name if s.project_id else ""
        limit = min(horizon, today + timedelta(days=7 * max(1, s.task_weeks)))  # N semaine(s) à l'avance
        self._prune_far_occurrences(s.id, limit)
        existing = {r["occurrence_date"] for r in self.db.conn.execute(
            "SELECT occurrence_date FROM tasks WHERE series_id=?", (s.id,))}
        with self.tasks.batch():
            for d in occurrences(s, max(today, s.start_date), limit):
                if iso_date(d) in existing:
                    continue
                try:
                    self.tasks.create(TaskInput(
                        title=s.title, project_name=project, description=s.description, assignee=s.assignee,
                        priority=s.priority, start_date=d, deadline=d, start_time=s.start_time, end_time=s.end_time,
                        est_minutes=s.est_minutes, space_id=s.space_id, source="Répétition", series_id=s.id,
                        occurrence_date=d), history=False)
                except ValidationError as exc:  # ex. projet archivé : on saute cette série
                    log.warning("Série %s ignorée : %s", s.id, exc)
                    break
                changed += 1
        return changed

    def _prune_far_occurrences(self, series_id: int, limit: date) -> None:
        """Réduction du délai : retire les occurrences intactes (à faire, sans commentaire ni pièce jointe) au-delà de la limite."""
        with self.db.transaction() as c:
            for r in c.execute(
                    """SELECT t.id FROM tasks t JOIN statuses s ON s.id=t.status_id WHERE t.series_id=? AND t.occurrence_date>?
                       AND t.deleted_at IS NULL AND s.kind='todo'
                       AND NOT EXISTS (SELECT 1 FROM comments m WHERE m.task_id=t.id)
                       AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.task_id=t.id)""", (series_id, iso_date(limit))).fetchall():
                c.execute("DELETE FROM tasks WHERE id=?", (r["id"],))

    def _sync_events(self, s: Recurrence, today: date, horizon: date) -> int:
        changed = 0
        templates = self.templates(s.id)
        task_limit = today + timedelta(days=7 * max(1, s.task_weeks))  # fenêtre de création des tâches modèles
        known = {r["date"]: r["id"] for r in self.db.conn.execute("SELECT id, date FROM events WHERE series_id=?", (s.id,))}
        with self.tasks.batch():
            for d in occurrences(s, max(today, s.start_date), horizon):
                if iso_date(d) in known:
                    event_id = known[iso_date(d)]
                else:
                    ev = self.events.create(EventInput(s.title, d, s.start_time, s.end_time, s.location, s.description, s.space_id),
                                            series_id=s.id)
                    event_id, changed = ev.id, changed + 1
                if templates and d <= task_limit:  # idempotent ; jamais recréée si supprimée
                    self._apply_templates(event_id, templates)
            # réduction de l'horizon : on retire les tâches modèles intactes des occurrences devenues trop lointaines
            for d_iso, event_id in known.items():
                if to_date(d_iso) > task_limit:
                    self._prune_template_tasks(event_id)
        return changed

    def _prune_template_tasks(self, event_id: int) -> None:
        with self.db.transaction() as c:
            for r in c.execute(
                    """SELECT t.id FROM tasks t JOIN statuses s ON s.id=t.status_id WHERE t.event_id=? AND t.template_id IS NOT NULL
                       AND t.deleted_at IS NULL AND s.kind='todo'
                       AND NOT EXISTS (SELECT 1 FROM comments m WHERE m.task_id=t.id)
                       AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.task_id=t.id)""", (event_id,)).fetchall():
                c.execute("DELETE FROM tasks WHERE id=?", (r["id"],))

    def _apply_templates(self, event_id: int, templates: list[EventTemplate]) -> None:
        have = {r["template_id"] for r in self.db.conn.execute(
            "SELECT template_id FROM tasks WHERE event_id=? AND template_id IS NOT NULL", (event_id,))}
        for t in templates:
            if t.id not in have:
                self.events.add_task(event_id, t.title, t.assignee, t.days_before, template_id=t.id)
