"""Événements (culte, réunion, cérémonie…) et tâches qui leur sont rattachées.

Un événement n'est **pas** une tâche : il n'entre dans aucun compteur, graphique, taux d'avancement ni retard.
Il sert de cadre : on lui rattache des tâches (« Chanter », « Lecture biblique »…) dont l'avancement
(« 3 / 4 faites ») s'affiche sur le tableau de bord et dans le planning.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

from ..db import Database
from .models import (
    Event, KIND_DONE, KIND_TODO, TaskInput, ValidationError, iso_date, iso_datetime, iso_time, to_date, to_datetime, to_time,
)
from .spaces import CURRENT, Scope
from .statuses import StatusService
from .tasks import TaskFilter, TaskService


@dataclass
class EventInput:
    title: str = ""
    date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location: str = ""
    description: str = ""
    space_id: Optional[int] = None  # None = espace courant


_SELECT = """
SELECT e.*,
  (SELECT COUNT(*) FROM tasks t WHERE t.event_id=e.id AND t.deleted_at IS NULL) AS n_tasks,
  (SELECT COUNT(*) FROM tasks t JOIN statuses s ON s.id=t.status_id
     WHERE t.event_id=e.id AND t.deleted_at IS NULL AND s.kind='done') AS n_done
FROM events e
"""


class EventService:
    def __init__(self, db: Database, tasks: TaskService, statuses: StatusService, scope: Scope,
                 clock: Callable[[], datetime] = datetime.now):
        self.db, self.tasks, self.statuses, self.scope, self.clock = db, tasks, statuses, scope, clock

    # ------------------------------------------------------------------ lecture
    @staticmethod
    def _row(r) -> Event:
        return Event(
            id=r["id"], space_id=r["space_id"], series_id=r["series_id"], title=r["title"], description=r["description"] or "",
            location=r["location"] or "", date=to_date(r["date"]), start_time=to_time(r["start_time"]),
            end_time=to_time(r["end_time"]), n_tasks=r["n_tasks"], n_done=r["n_done"], deleted_at=to_datetime(r["deleted_at"]))

    def get(self, event_id: int) -> Event:
        r = self.db.conn.execute(_SELECT + " WHERE e.id=?", (event_id,)).fetchone()
        if r is None:
            raise ValidationError("Événement introuvable.")
        return self._row(r)

    def list(self, frm: Optional[date] = None, to: Optional[date] = None, space_id=CURRENT) -> list[Event]:
        where, params = ["e.deleted_at IS NULL"], []
        sp = self.scope.resolve(space_id)
        if sp is not None:
            where.append("e.space_id=?"); params.append(sp)
        if frm:
            where.append("e.date>=?"); params.append(iso_date(frm))
        if to:
            where.append("e.date<=?"); params.append(iso_date(to))
        sql = _SELECT + " WHERE " + " AND ".join(where) + " ORDER BY e.date, e.start_time IS NULL, e.start_time, e.id"
        return [self._row(r) for r in self.db.conn.execute(sql, params)]

    def linked_tasks(self, event_id: int):
        return self.tasks.list(TaskFilter(event_id=event_id, space_id=None, sort="deadline"))

    # ------------------------------------------------------------------ validation / écriture
    def validate(self, d: EventInput) -> None:
        if not (d.title or "").strip():
            raise ValidationError("L'intitulé de l'événement est obligatoire.")
        if d.date is None:
            raise ValidationError("Indiquez la date de l'événement.")
        if d.end_time and not d.start_time:
            raise ValidationError("Renseignez l'heure de début avant l'heure de fin.")
        if d.start_time and d.end_time and d.end_time <= d.start_time:
            raise ValidationError("L'heure de fin doit être postérieure à l'heure de début.")

    def create(self, d: EventInput, new_tasks: Optional[list] = None, series_id: Optional[int] = None) -> Event:
        """Crée un événement (+ tâches liées ``new_tasks`` : liste de (intitulé, responsable, jours_avant))."""
        self.validate(d)
        sp = d.space_id or self.scope.space_id or 1
        with self.tasks.batch(), self.db.transaction() as c:
            cur = c.execute(
                "INSERT INTO events(space_id,series_id,title,description,location,date,start_time,end_time,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (sp, series_id, d.title.strip(), (d.description or "").strip(), (d.location or "").strip(), iso_date(d.date),
                 iso_time(d.start_time), iso_time(d.end_time), iso_datetime(self.clock())))
            event_id = cur.lastrowid
            for item in new_tasks or []:
                self.add_task(event_id, item[0], item[1] if len(item) > 1 else "", item[2] if len(item) > 2 else 0)
        return self.get(event_id)

    def update(self, event_id: int, d: EventInput) -> Event:
        self.validate(d)
        with self.db.transaction() as c:
            c.execute("UPDATE events SET title=?,description=?,location=?,date=?,start_time=?,end_time=? WHERE id=?",
                      (d.title.strip(), (d.description or "").strip(), (d.location or "").strip(), iso_date(d.date),
                       iso_time(d.start_time), iso_time(d.end_time), event_id))
        self.tasks.notify_changed()
        return self.get(event_id)

    def delete(self, event_id: int, delete_tasks: bool = False) -> None:
        """Supprime l'événement (corbeille logique : une occurrence de série n'est jamais recréée).
        Les tâches liées sont détachées, ou mises à la corbeille avec ``delete_tasks``."""
        linked = self.linked_tasks(event_id) if delete_tasks else []
        with self.tasks.batch():
            for t in linked:
                self.tasks.delete(t.id)
            with self.db.transaction() as c:
                c.execute("UPDATE tasks SET event_id=NULL WHERE event_id=?", (event_id,))
                c.execute("UPDATE events SET deleted_at=? WHERE id=?", (iso_datetime(self.clock()), event_id))

    # ------------------------------------------------------------------ tâches liées
    def add_task(self, event_id: int, title: str, assignee: str = "", days_before: int = 0,
                 template_id: Optional[int] = None, deadline: Optional[date] = None):
        """Crée une tâche rattachée à l'événement (échéance = date de l'événement moins ``days_before``)."""
        ev = self.get(event_id)
        due = deadline or (ev.date - timedelta(days=max(0, days_before)))
        return self.tasks.create(TaskInput(
            title=title, assignee=assignee, start_date=due, deadline=due, space_id=ev.space_id,
            source="Événement", event_id=event_id, template_id=template_id), history=True)

    def link(self, task_id: int, event_id: Optional[int]):
        t = self.tasks.get(task_id)
        data = self.tasks.to_input(t, event_id=event_id)
        if event_id and not (t.deadline or t.start_date):  # tâche sans date : elle prend celle de l'événement
            ev = self.get(event_id)
            data.start_date = data.deadline = ev.date
        return self.tasks.update(task_id, data, strict=False)

    def is_untouched(self, event_id: int) -> bool:
        """Aucune tâche liée n'a été traitée, commentée ou complétée avec une pièce jointe."""
        row = self.db.conn.execute(
            """SELECT COUNT(*) FROM tasks t JOIN statuses s ON s.id=t.status_id WHERE t.event_id=? AND t.deleted_at IS NULL AND
               (s.kind<>'todo' OR t.template_id IS NULL
                OR EXISTS (SELECT 1 FROM comments m WHERE m.task_id=t.id)
                OR EXISTS (SELECT 1 FROM attachments a WHERE a.task_id=t.id))""", (event_id,)).fetchone()
        return row[0] == 0

    def purge(self, event_id: int) -> None:
        """Suppression physique d'un événement intact et de ses tâches modèles (usage interne : séries)."""
        with self.db.transaction() as c:
            c.execute("DELETE FROM tasks WHERE event_id=?", (event_id,))
            c.execute("DELETE FROM events WHERE id=?", (event_id,))
