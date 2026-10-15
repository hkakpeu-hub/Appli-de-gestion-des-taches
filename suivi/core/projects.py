"""Gestion des projets."""
from __future__ import annotations

import itertools
from datetime import datetime
from typing import Optional

from ..db import Database
from .models import DATETIME_FMT, Project, ValidationError

PALETTE = ["#2563EB", "#16A34A", "#D97706", "#9333EA", "#0891B2", "#DB2777", "#65A30D", "#EA580C", "#4F46E5", "#0D9488"]


class ProjectService:
    def __init__(self, db: Database):
        self.db = db
        self._listeners: list = []

    def subscribe(self, cb) -> None:
        self._listeners.append(cb)

    def _notify(self) -> None:
        for cb in self._listeners:
            cb()

    @staticmethod
    def _row(r) -> Project:
        return Project(r["id"], r["name"], r["color"], r["description"], bool(r["archived"]))

    def list(self, include_archived: bool = True) -> list[Project]:
        sql = "SELECT * FROM projects" + ("" if include_archived else " WHERE archived=0") + " ORDER BY name COLLATE NOCASE"
        return [self._row(r) for r in self.db.conn.execute(sql)]

    def get(self, project_id: int) -> Project:
        r = self.db.conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if r is None:
            raise ValidationError("Projet introuvable.")
        return self._row(r)

    def by_name(self, name: str) -> Optional[Project]:
        r = self.db.conn.execute("SELECT * FROM projects WHERE name=?", (name.strip(),)).fetchone()
        return self._row(r) if r else None

    def get_or_create(self, name: str) -> Optional[Project]:
        """Retourne le projet nommé (créé au besoin). Nom vide -> None (tâche sans projet)."""
        name = " ".join((name or "").split())
        if not name:
            return None
        existing = self.by_name(name)
        if existing:
            return existing
        color = PALETTE[self.db.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] % len(PALETTE)]
        with self.db.transaction() as c:
            cur = c.execute(
                "INSERT INTO projects(name,color,created_at) VALUES (?,?,?)",
                (name, color, datetime.now().strftime(DATETIME_FMT)),
            )
        self._notify()
        return self.get(cur.lastrowid)

    def create(self, name: str, color: Optional[str] = None, description: str = "") -> Project:
        name = " ".join((name or "").split())
        if not name:
            raise ValidationError("Le nom du projet est obligatoire.")
        if self.by_name(name):
            raise ValidationError(f"Le projet « {name} » existe déjà.")
        p = self.get_or_create(name)
        if color or description:
            self.update(p.id, name, color or p.color, description)
        return self.get(p.id)

    def update(self, project_id: int, name: str, color: Optional[str], description: str = "", archived: bool = False) -> None:
        name = " ".join((name or "").split())
        if not name:
            raise ValidationError("Le nom du projet est obligatoire.")
        other = self.by_name(name)
        if other and other.id != project_id:
            raise ValidationError(f"Le projet « {name} » existe déjà.")
        with self.db.transaction() as c:
            c.execute(
                "UPDATE projects SET name=?, color=?, description=?, archived=? WHERE id=?",
                (name, color, description, 1 if archived else 0, project_id),
            )
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
