"""Gestion des tâches : CRUD, validation, filtres, commentaires, historique."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from ..db import Database, fold
from .models import (
    CLOSED_KINDS,
    DATETIME_FMT,
    KIND_DONE,
    KIND_TODO,
    PRIORITIES,
    PRIORITY_LABELS,
    Comment,
    HistoryEvent,
    Task,
    TaskInput,
    ValidationError,
    iso_date,
    iso_datetime,
    iso_time,
    to_date,
    to_datetime,
)
from .projects import ProjectService
from .spaces import CURRENT, Scope
from .statuses import StatusService

BASE_SELECT = """
SELECT t.*, p.name AS project_name, p.color AS project_color,
       s.label AS status_label, s.kind AS status_kind, s.color AS status_color,
       (SELECT COUNT(*) FROM attachments a WHERE a.task_id = t.id) AS n_attach
FROM tasks t
LEFT JOIN projects p ON p.id = t.project_id
JOIN statuses s ON s.id = t.status_id
"""

SORT_COLUMNS = {
    "deadline": "(t.deadline IS NULL), t.deadline",
    "priority": "CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END",
    "project": "fold(p.name)",
    "created": "t.created_at",
    "status": "s.position",
    "start": "(t.start_date IS NULL), t.start_date",
    "title": "fold(t.title)",
    "updated": "t.updated_at",
    "assignee": "fold(t.assignee)",
}

FIELD_LABELS = {
    "title": "Intitulé",
    "project": "Projet",
    "description": "Description",
    "assignee": "Responsable",
    "start_date": "Date de début",
    "deadline": "Deadline",
    "status": "Statut",
    "priority": "Priorité",
    "start_time": "Heure de début",
    "end_time": "Heure de fin",
    "est_minutes": "Durée estimée (min)",
    "actual_minutes": "Durée réelle (min)",
    "completed_at": "Réalisée le",
}

EVENT_LABELS = {
    "created": "Création",
    "updated": "Modification",
    "status": "Changement de statut",
    "deadline": "Modification de deadline",
    "priority": "Changement de priorité",
    "comment": "Commentaire ajouté",
    "completed": "Clôture",
    "reopened": "Réouverture",
    "deleted": "Suppression (corbeille)",
    "restored": "Restauration",
    "imported": "Import",
}


@dataclass
class TaskFilter:
    text: str = ""
    project_ids: list[int] = field(default_factory=list)
    status_ids: list[int] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    assignee: str = ""
    priorities: list[str] = field(default_factory=list)
    date_field: str = "deadline"  # deadline | start_date | created_at
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    delay: Optional[str] = None  # none | any | light | moderate | severe
    only_active: bool = False
    no_deadline: bool = False
    updated_after: Optional[datetime] = None
    updated_before: Optional[datetime] = None
    today_view: bool = False  # échéance ou début aujourd'hui, ou tâche en cours
    involving: Optional[tuple[date, date]] = None  # deadline OU début dans l'intervalle
    sort: str = "deadline"
    descending: bool = False
    space_id: object = CURRENT  # None = tous les espaces
    include_archived: bool = False  # tâches des projets archivés : masquées par défaut

    def is_empty(self) -> bool:
        return self == TaskFilter()


class TaskService:
    def __init__(
        self,
        db: Database,
        projects: ProjectService,
        statuses: StatusService,
        clock: Callable[[], datetime] = datetime.now,
        scope: Optional[Scope] = None,
    ):
        self.scope = scope or projects.scope
        self.db = db
        self.projects = projects
        self.statuses = statuses
        self.clock = clock
        self._listeners: list[Callable[[], None]] = []
        self._muted = 0

    # ------------------------------------------------------------ événements
    def subscribe(self, cb: Callable[[], None]) -> None:
        self._listeners.append(cb)

    def _notify(self) -> None:
        if self._muted:
            return
        for cb in list(self._listeners):
            cb()

    def notify_changed(self) -> None:
        self._notify()

    # ----------------------------------------------------------------- lecture
    def get(self, task_id: int) -> Task:
        r = self.db.conn.execute(BASE_SELECT + " WHERE t.id=?", (task_id,)).fetchone()
        if r is None:
            raise ValidationError("Tâche introuvable.")
        return Task.from_row(r)

    def _scope_sql(self, space_id, include_archived: bool, include_deleted: bool = False) -> tuple[list[str], list]:
        where, params = [], []
        if not include_deleted:
            where.append("t.deleted_at IS NULL")
        sp = self.scope.resolve(space_id)
        if sp is not None:
            where.append("t.space_id=?")
            params.append(sp)
        if not include_archived:  # projet archivé => tâches invisibles partout
            where.append("(p.archived IS NULL OR p.archived=0)")
        return where, params

    def all(self, include_deleted: bool = False, include_archived: bool = False, space_id=CURRENT) -> list[Task]:
        where, params = self._scope_sql(space_id, include_archived, include_deleted)
        sql = BASE_SELECT + (" WHERE " + " AND ".join(where) if where else "")
        return [Task.from_row(r) for r in self.db.conn.execute(sql, params)]

    def deleted(self, space_id=CURRENT) -> list[Task]:
        where, params = self._scope_sql(space_id, False, True)
        where.append("t.deleted_at IS NOT NULL")
        sql = BASE_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY t.deleted_at DESC"
        return [Task.from_row(r) for r in self.db.conn.execute(sql, params)]

    def assignees(self, space_id=CURRENT) -> list[str]:
        where, params = self._scope_sql(space_id, False)
        rows = self.db.conn.execute(
            "SELECT DISTINCT t.assignee FROM tasks t LEFT JOIN projects p ON p.id=t.project_id "
            "WHERE t.assignee<>'' AND " + " AND ".join(where) + " ORDER BY t.assignee COLLATE NOCASE", params)
        return [r[0] for r in rows]

    def count(self, flt: Optional[TaskFilter] = None, today: Optional[date] = None) -> int:
        return len(self.list(flt or TaskFilter(), today))

    def list(self, flt: Optional[TaskFilter] = None, today: Optional[date] = None) -> list[Task]:
        flt = flt or TaskFilter()
        today = today or self.clock().date()
        where, params = self._scope_sql(flt.space_id, flt.include_archived)
        closed = ",".join(f"'{k}'" for k in CLOSED_KINDS)
        active = f"s.kind NOT IN ({closed})"

        if flt.text.strip():
            for word in flt.text.split():
                like = f"%{fold(word)}%"
                where.append(
                    "(fold(t.title) LIKE ? OR fold(t.description) LIKE ? OR fold(p.name) LIKE ? "
                    "OR fold(t.assignee) LIKE ? OR EXISTS (SELECT 1 FROM comments c WHERE c.task_id=t.id AND fold(c.body) LIKE ?))"
                )
                params += [like] * 5
        if flt.project_ids:
            marks = ",".join("?" * len(flt.project_ids))
            where.append(f"t.project_id IN ({marks})")
            params += flt.project_ids
        if flt.status_ids:
            where.append(f"t.status_id IN ({','.join('?' * len(flt.status_ids))})")
            params += flt.status_ids
        if flt.kinds:
            where.append(f"s.kind IN ({','.join('?' * len(flt.kinds))})")
            params += flt.kinds
        if flt.assignee:
            where.append("fold(t.assignee)=?")
            params.append(fold(flt.assignee))
        if flt.priorities:
            where.append(f"t.priority IN ({','.join('?' * len(flt.priorities))})")
            params += flt.priorities
        if flt.only_active:
            where.append(active)
        if flt.no_deadline:
            where.append("t.deadline IS NULL")
        if flt.updated_after:
            where.append("t.updated_at >= ?")
            params.append(iso_datetime(flt.updated_after))
        if flt.updated_before:
            where.append("t.updated_at <= ?")
            params.append(iso_datetime(flt.updated_before))
        col = {"deadline": "t.deadline", "start_date": "t.start_date", "created_at": "substr(t.created_at,1,10)"}.get(
            flt.date_field, "t.deadline"
        )
        if flt.date_from:
            where.append(f"{col} >= ?")
            params.append(iso_date(flt.date_from))
        if flt.date_to:
            where.append(f"{col} <= ?")
            params.append(iso_date(flt.date_to))
        if flt.involving:
            a, b = (iso_date(x) for x in flt.involving)
            where.append("((t.deadline BETWEEN ? AND ?) OR (t.start_date BETWEEN ? AND ?))")
            params += [a, b, a, b]
        if flt.today_view:
            iso = iso_date(today)
            where.append(f"{active} AND (t.deadline=? OR t.start_date=? OR s.kind='in_progress')")
            params += [iso, iso]
        if flt.delay:
            iso = iso_date(today)
            dd = "(julianday(?) - julianday(t.deadline))"
            base = f"{active} AND t.deadline IS NOT NULL AND "
            if flt.delay == "any":
                where.append(base + "t.deadline < ?")
                params.append(iso)
            elif flt.delay == "none":
                where.append(f"NOT ({base} t.deadline < ?)")
                params.append(iso)
            else:
                lo, hi = {"light": (1, 3), "moderate": (4, 14), "severe": (15, 100000)}[flt.delay]
                where.append(f"{base}{dd} BETWEEN ? AND ?")
                params += [iso, lo, hi]

        order_col = SORT_COLUMNS.get(flt.sort, SORT_COLUMNS["deadline"])
        direction = "DESC" if flt.descending else "ASC"
        if flt.sort == "deadline":  # les tâches sans deadline restent en fin de liste dans les deux sens
            order = f"(t.deadline IS NULL), t.deadline {direction}"
        else:
            order = f"{order_col} {direction}"
        sql = f"{BASE_SELECT} WHERE {' AND '.join(where)} ORDER BY {order}, t.id"
        return [Task.from_row(r) for r in self.db.conn.execute(sql, params)]

    # -------------------------------------------------------------- validation
    def validate(self, data: TaskInput, strict: bool = True) -> None:
        title = (data.title or "").strip()
        if not title:
            raise ValidationError("L'intitulé de la tâche est obligatoire.")
        if len(title) > 500:
            raise ValidationError("L'intitulé est trop long (500 caractères maximum).")
        if data.priority not in PRIORITIES:
            raise ValidationError("Priorité invalide.")
        if strict and data.start_date and data.deadline and data.deadline < data.start_date:
            raise ValidationError("La deadline ne peut pas être antérieure à la date de début.")
        if (data.start_time or data.end_time) and not data.start_date:
            raise ValidationError("Renseignez une date de début pour planifier des horaires.")
        if data.start_time and data.end_time and data.end_time <= data.start_time:
            raise ValidationError("L'heure de fin doit être postérieure à l'heure de début.")
        for name, val in (("estimée", data.est_minutes), ("réelle", data.actual_minutes)):
            if val is not None and val < 0:
                raise ValidationError(f"La durée {name} ne peut pas être négative.")

    # ---------------------------------------------------------------- écriture
    def _history(self, c, task_id, title, event, field_name="", old="", new="", at=None) -> None:
        c.execute(
            "INSERT INTO history(task_id,task_title,event,field,old_value,new_value,at) VALUES (?,?,?,?,?,?,?)",
            (task_id, title, event, field_name, old or "", new or "", iso_datetime(at or self.clock())),
        )

    def log_event(self, task_id, title, event, field_name="", old="", new="") -> None:
        with self.db.transaction() as c:
            self._history(c, task_id, title, event, field_name, old, new)

    def create(self, data: TaskInput, history: bool = True, strict: bool = True, completed_default_now: bool = True) -> Task:
        self.validate(data, strict)
        now = self.clock()
        space_id = data.space_id or self.scope.space_id or 1
        project = self._project_for(data.project_name, space_id)
        status_id = data.status_id or self.statuses.first_of_kind(KIND_TODO).id
        status = self.statuses.get(status_id)
        completed = data.completed_at
        if status.kind == KIND_DONE and completed is None and completed_default_now:
            completed = now
        if status.kind != KIND_DONE:
            completed = None
        created = data.created_at or now
        with self.db.transaction() as c:
            cur = c.execute(
                """INSERT INTO tasks(title,project_id,description,assignee,created_at,start_date,deadline,status_id,
                   priority,completed_at,start_time,end_time,est_minutes,actual_minutes,extra_date,source,
                   updated_at,status_changed_at,space_id,series_id,occurrence_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.title.strip(), project.id if project else None, (data.description or "").strip(),
                    (data.assignee or "").strip(), iso_datetime(created), iso_date(data.start_date),
                    iso_date(data.deadline), status_id, data.priority, iso_datetime(completed),
                    iso_time(data.start_time), iso_time(data.end_time), data.est_minutes, data.actual_minutes,
                    iso_date(data.extra_date), data.source, iso_datetime(now), iso_datetime(now), space_id,
                    data.series_id, iso_date(data.occurrence_date),
                ),
            )
            task_id = cur.lastrowid
            if history:
                self._history(c, task_id, data.title.strip(), "created", new=status.label, at=now)
            for body in data.comments:
                if body.strip():
                    c.execute(
                        "INSERT INTO comments(task_id,body,created_at) VALUES (?,?,?)",
                        (task_id, body.strip(), iso_datetime(created)),
                    )
        self._notify()
        return self.get(task_id)

    def _project_for(self, name: str, space_id: int):
        project = self.projects.get_or_create(name, space_id)
        if project and project.archived:
            raise ValidationError(f"Le projet « {project.name} » est archivé : désarchivez-le ou choisissez un autre projet.")
        return project

    def move_to_space(self, task_id: int, space_id: int) -> Task:
        """Déplace une tâche vers un autre espace (le projet est recréé/retrouvé par son nom dans l'espace cible)."""
        t = self.get(task_id)
        if t.space_id == space_id:
            return t
        project = self.projects.get_or_create(t.project_name, space_id)
        now = self.clock()
        with self.db.transaction() as c:
            c.execute("UPDATE tasks SET space_id=?, project_id=?, updated_at=? WHERE id=?",
                      (space_id, project.id if project else None, iso_datetime(now), task_id))
            c.execute("UPDATE alerts SET resolved_at=? WHERE task_id=? AND resolved_at IS NULL", (iso_datetime(now), task_id))
            self._history(c, task_id, t.title, "updated", "Espace", str(t.space_id), str(space_id), now)
        self._notify()
        return self.get(task_id)

    def _fields_of(self, t: Task) -> dict:
        return {
            "title": t.title, "project": t.project_name, "description": t.description, "assignee": t.assignee,
            "start_date": t.start_date, "deadline": t.deadline, "status": t.status_id, "priority": t.priority,
            "start_time": t.start_time, "end_time": t.end_time, "est_minutes": t.est_minutes,
            "actual_minutes": t.actual_minutes,
        }

    @staticmethod
    def _fmt(name: str, v) -> str:
        if v in (None, ""):
            return ""
        if name == "priority":
            return PRIORITY_LABELS.get(v, str(v))
        if isinstance(v, date) and not isinstance(v, datetime):
            return v.strftime("%d/%m/%Y")
        if hasattr(v, "strftime"):
            return v.strftime("%H:%M")
        return str(v)

    def update(self, task_id: int, data: TaskInput, strict: bool = True) -> Task:
        """Modifie une tâche et journalise chaque champ réellement modifié."""
        self.validate(data, strict)
        old = self.get(task_id)
        now = self.clock()
        project = (self._project_for(data.project_name, old.space_id)
                   if (data.project_name or "").strip() != old.project_name else
                   (self.projects.get(old.project_id) if old.project_id else None))
        new_status = self.statuses.get(data.status_id or old.status_id)
        status_changed = new_status.id != old.status_id
        completed = old.completed_at
        events: list[tuple] = []
        if status_changed:
            if new_status.kind == KIND_DONE:
                completed = data.completed_at or now
            else:
                completed = None
        elif new_status.kind == KIND_DONE and data.completed_at:
            completed = data.completed_at

        before = self._fields_of(old)
        after = {
            "title": data.title.strip(), "project": project.name if project else "",
            "description": (data.description or "").strip(), "assignee": (data.assignee or "").strip(),
            "start_date": data.start_date, "deadline": data.deadline, "status": new_status.id,
            "priority": data.priority, "start_time": data.start_time, "end_time": data.end_time,
            "est_minutes": data.est_minutes, "actual_minutes": data.actual_minutes,
        }
        for name, newv in after.items():
            oldv = before[name]
            if (oldv or None) == (newv or None):
                continue
            if name == "status":
                events.append(("completed" if new_status.kind == KIND_DONE else
                               ("reopened" if old.status_kind == KIND_DONE else "status"),
                               "status", old.status_label, new_status.label))
            elif name in ("deadline", "priority"):
                events.append((name, name, self._fmt(name, oldv), self._fmt(name, newv)))
            else:
                events.append(("updated", name, self._fmt(name, oldv)[:200], self._fmt(name, newv)[:200]))
        if not events and completed == old.completed_at:
            return old  # rien n'a changé : aucun bruit dans l'historique

        with self.db.transaction() as c:
            c.execute(
                """UPDATE tasks SET title=?,project_id=?,description=?,assignee=?,start_date=?,deadline=?,status_id=?,
                   priority=?,completed_at=?,start_time=?,end_time=?,est_minutes=?,actual_minutes=?,extra_date=?,
                   updated_at=?, status_changed_at=? WHERE id=?""",
                (
                    after["title"], project.id if project else None, after["description"], after["assignee"],
                    iso_date(data.start_date), iso_date(data.deadline), new_status.id, data.priority,
                    iso_datetime(completed), iso_time(data.start_time), iso_time(data.end_time),
                    data.est_minutes, data.actual_minutes,
                    iso_date(data.extra_date) if data.extra_date is not None else iso_date(old.extra_date),
                    iso_datetime(now), iso_datetime(now if status_changed else old.status_changed_at), task_id,
                ),
            )
            for ev, name, o, n in events:
                self._history(c, task_id, after["title"], ev, FIELD_LABELS.get(name, name), o, n, now)
        self._notify()
        return self.get(task_id)

    def set_status(self, task_id: int, status_id: int) -> Task:
        t = self.get(task_id)
        return self.update(task_id, self.to_input(t, status_id=status_id))

    def complete(self, task_id: int) -> Task:
        return self.set_status(task_id, self.statuses.first_of_kind(KIND_DONE).id)

    def set_schedule(self, task_id: int, day: date, start, end) -> Task:
        """Déplace/redimensionne une tâche dans le planning."""
        t = self.get(task_id)
        data = self.to_input(t)
        data.start_date, data.start_time, data.end_time = day, start, end
        if data.deadline and data.deadline < day:
            data.deadline = day
        return self.update(task_id, data)

    @staticmethod
    def to_input(t: Task, **over) -> TaskInput:
        data = TaskInput(
            title=t.title, project_name=t.project_name, description=t.description, assignee=t.assignee,
            start_date=t.start_date, deadline=t.deadline, status_id=t.status_id, priority=t.priority,
            start_time=t.start_time, end_time=t.end_time, est_minutes=t.est_minutes,
            actual_minutes=t.actual_minutes, extra_date=t.extra_date, source=t.source,
        )
        return replace(data, **over)

    # --------------------------------------------------- suppression douce
    def delete(self, task_id: int) -> None:
        """Place la tâche dans la corbeille (récupérable). Voir ``purge`` pour l'effacement définitif."""
        t = self.get(task_id)
        now = self.clock()
        with self.db.transaction() as c:
            c.execute("UPDATE tasks SET deleted_at=? WHERE id=?", (iso_datetime(now), task_id))
            c.execute("UPDATE alerts SET resolved_at=? WHERE task_id=? AND resolved_at IS NULL", (iso_datetime(now), task_id))
            self._history(c, task_id, t.title, "deleted", at=now)
        self._notify()

    def restore(self, task_id: int) -> None:
        t = self.get(task_id)
        with self.db.transaction() as c:
            c.execute("UPDATE tasks SET deleted_at=NULL WHERE id=?", (task_id,))
            self._history(c, task_id, t.title, "restored")
        self._notify()

    def purge(self, task_id: int) -> None:
        """Suppression DÉFINITIVE (irréversible hors sauvegarde). L'historique est conservé."""
        t = self.get(task_id)
        with self.db.transaction() as c:
            self._history(c, None, t.title, "deleted", "définitif")
            c.execute("UPDATE history SET task_id=NULL WHERE task_id=?", (task_id,))
            c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self._notify()

    # -------------------------------------------------- commentaires/historique
    def add_comment(self, task_id: int, body: str) -> Comment:
        body = (body or "").strip()
        if not body:
            raise ValidationError("Le commentaire est vide.")
        t = self.get(task_id)
        now = self.clock()
        with self.db.transaction() as c:
            cur = c.execute(
                "INSERT INTO comments(task_id,body,created_at) VALUES (?,?,?)", (task_id, body, iso_datetime(now))
            )
            c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (iso_datetime(now), task_id))
            self._history(c, task_id, t.title, "comment", "Commentaire", "", body[:200], now)
        self._notify()
        return Comment(cur.lastrowid, task_id, body, now)

    def comments(self, task_id: int) -> list[Comment]:
        rows = self.db.conn.execute("SELECT * FROM comments WHERE task_id=? ORDER BY created_at DESC, id DESC", (task_id,))
        return [Comment(r["id"], r["task_id"], r["body"], to_datetime(r["created_at"])) for r in rows]

    def history(self, task_id: Optional[int] = None, limit: int = 500, event: str = "", text: str = "",
                space_id=None) -> list[HistoryEvent]:
        where, params = [], []
        sp = self.scope.resolve(space_id)
        if sp is not None:
            where.append("task_id IN (SELECT id FROM tasks WHERE space_id=?)")
            params.append(sp)
        if task_id is not None:
            where.append("task_id=?")
            params.append(task_id)
        if event:
            where.append("event=?")
            params.append(event)
        if text.strip():
            where.append("(fold(task_title) LIKE ? OR fold(new_value) LIKE ? OR fold(old_value) LIKE ?)")
            params += [f"%{fold(text)}%"] * 3
        sql = "SELECT * FROM history" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY at DESC, id DESC LIMIT ?"
        rows = self.db.conn.execute(sql, params + [limit])
        return [
            HistoryEvent(r["id"], r["task_id"], r["task_title"] or "", r["event"], r["field"] or "",
                         r["old_value"] or "", r["new_value"] or "", to_datetime(r["at"]))
            for r in rows
        ]

    # ------------------------------------------------------------------ lots
    def batch(self):
        """Contexte : regroupe plusieurs opérations et ne notifie l'interface qu'à la fin."""
        svc = self

        class _Batch:
            def __enter__(self_inner):
                svc._muted += 1

            def __exit__(self_inner, *exc):
                svc._muted -= 1
                if svc._muted == 0:
                    svc._notify()

        return _Batch()
