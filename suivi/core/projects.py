"""Gestion des projets (rattachés à un espace).

Un projet **archivé** disparaît de tout : ses tâches ne sont plus listées, comptées, alertées ni exportées
(sauf demande explicite), mais rien n'est supprimé — désarchiver le projet les restitue intégralement.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..db import Database
from .models import DATETIME_FMT, Project, ValidationError
from .spaces import CURRENT, Scope

PALETTE = ["#2563EB", "#16A34A", "#D97706", "#9333EA", "#0891B2", "#DB2777", "#65A30D", "#EA580C", "#4F46E5", "#0D9488"]


class ProjectService:
    def __init__(self, db: Database, scope: Optional[Scope] = None):
        self.db = db
        self.scope = scope or Scope(1)
        self._listeners: list = []

    def subscribe(self, cb) -> None:
        self._listeners.append(cb)

    def _notify(self) -> None:
        for cb in self._listeners:
            cb()

    def _space(self, space_id) -> Optional[int]:
        return self.scope.resolve(space_id)

    @staticmethod
    def _row(r) -> Project:
        return Project(r["id"], r["space_id"], r["name"], r["color"], r["description"], bool(r["archived"]))

    def list(self, include_archived: bool = True, space_id=CURRENT) -> list[Project]:
        where, params = [], []
        sp = self._space(space_id)
        if sp is not None:
            where.append("space_id=?")
            params.append(sp)
        if not include_archived:
            where.append("archived=0")
        sql = "SELECT * FROM projects" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY name COLLATE NOCASE"
        return [self._row(r) for r in self.db.conn.execute(sql, params)]

    def archived_count(self, space_id=CURRENT) -> int:
        sp = self._space(space_id)
        sql = "SELECT COUNT(*) FROM projects WHERE archived=1" + (" AND space_id=?" if sp is not None else "")
        return self.db.conn.execute(sql, [sp] if sp is not None else []).fetchone()[0]

    def get(self, project_id: int) -> Project:
        r = self.db.conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if r is None:
            raise ValidationError("Projet introuvable.")
        return self._row(r)

    def by_name(self, name: str, space_id=CURRENT) -> Optional[Project]:
        sp = self._space(space_id)
        r = self.db.conn.execute("SELECT * FROM projects WHERE name=? AND space_id=?", (name.strip(), sp if sp is not None else 1)).fetchone()
        return self._row(r) if r else None

    def get_or_create(self, name: str, space_id=CURRENT) -> Optional[Project]:
        """Retourne le projet nommé de l'espace (créé au besoin). Nom vide -> None (tâche sans projet)."""
        name = " ".join((name or "").split())
        if not name:
            return None
        sp = self._space(space_id)
        sp = 1 if sp is None else sp
        existing = self.by_name(name, sp)
        if existing:
            return existing
        color = PALETTE[self.db.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] % len(PALETTE)]
        with self.db.transaction() as c:
            cur = c.execute(
                "INSERT INTO projects(space_id,name,color,created_at) VALUES (?,?,?,?)",
                (sp, name, color, datetime.now().strftime(DATETIME_FMT)),
            )
        self._notify()
        return self.get(cur.lastrowid)

    def create(self, name: str, color: Optional[str] = None, description: str = "", space_id=CURRENT) -> Project:
        name = " ".join((name or "").split())
        if not name:
            raise ValidationError("Le nom du projet est obligatoire.")
        if self.by_name(name, space_id):
            raise ValidationError(f"Le projet « {name} » existe déjà dans cet espace.")
        p = self.get_or_create(name, space_id)
        if color or description:
            self.update(p.id, name, color or p.color, description)
        return self.get(p.id)

    def update(self, project_id: int, name: str, color: Optional[str], description: str = "", archived: bool = False) -> None:
        name = " ".join((name or "").split())
        if not name:
            raise ValidationError("Le nom du projet est obligatoire.")
        cur = self.get(project_id)
        other = self.by_name(name, cur.space_id)
        if other and other.id != project_id:
            raise ValidationError(f"Le projet « {name} » existe déjà dans cet espace.")
        with self.db.transaction() as c:
            c.execute(
                "UPDATE projects SET name=?, color=?, description=?, archived=? WHERE id=?",
                (name, color, description, 1 if archived else 0, project_id),
            )
        self._notify()

    def set_archived(self, project_id: int, archived: bool) -> None:
        """Archive / désarchive un projet. Ses tâches sont masquées (ou restituées) partout."""
        with self.db.transaction() as c:
            c.execute("UPDATE projects SET archived=? WHERE id=?", (1 if archived else 0, project_id))
            if archived:  # les alertes en cours de ces tâches n'ont plus lieu d'être
                c.execute("UPDATE alerts SET resolved_at=COALESCE(resolved_at, ?) WHERE task_id IN "
                          "(SELECT id FROM tasks WHERE project_id=?)", (datetime.now().strftime(DATETIME_FMT), project_id))
        self._notify()

    def delete(self, project_id: int) -> None:
        n = self.db.conn.execute("SELECT COUNT(*) FROM tasks WHERE project_id=?", (project_id,)).fetchone()[0]
        if n:
            raise ValidationError(
                f"Ce projet contient {n} tâche(s). Archivez-le ou déplacez d'abord ses tâches."
            )
        with self.db.transaction() as c:
            c.execute("DELETE FROM projects WHERE id=?", (project_id,))
        self._notify()
