"""Espaces de gestion (Travail, Personnel, Kingdom…) et « portée » courante.

Chaque espace a ses propres projets et tâches. La portée (``Scope``) indique l'espace affiché ;
``space_id=None`` dans une requête signifie « tous les espaces » (alertes globales, accueil).
"""
from __future__ import annotations

from typing import Callable, Optional

from ..db import Database
from .models import Space, ValidationError

CURRENT = "current"  # sentinelle : utiliser l'espace courant de la portée


class Scope:
    def __init__(self, space_id: Optional[int] = 1):
        self.space_id = space_id
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, cb: Callable[[], None]) -> None:
        self._listeners.append(cb)

    def set(self, space_id: Optional[int]) -> None:
        self.space_id = space_id
        for cb in list(self._listeners):
            cb()

    def resolve(self, space_id) -> Optional[int]:
        return self.space_id if space_id == CURRENT else space_id


class SpaceService:
    def __init__(self, db: Database):
        self.db = db
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, cb) -> None:
        self._listeners.append(cb)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    @staticmethod
    def _row(r) -> Space:
        return Space(r["id"], r["name"], r["icon"], r["color"], r["kind"], r["position"], bool(r["enabled"]))

    def list(self, enabled_only: bool = False) -> list[Space]:
        sql = "SELECT * FROM spaces" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY position, id"
        return [self._row(r) for r in self.db.conn.execute(sql)]

    def get(self, space_id: int) -> Space:
        r = self.db.conn.execute("SELECT * FROM spaces WHERE id=?", (space_id,)).fetchone()
        if r is None:
            raise ValidationError("Espace introuvable.")
        return self._row(r)

    def by_name(self, name: str) -> Optional[Space]:
        r = self.db.conn.execute("SELECT * FROM spaces WHERE name=?", (name.strip(),)).fetchone()
        return self._row(r) if r else None

    def create(self, name: str, icon: str = "✔", color: str = "#2563EB", kind: str = "tasks") -> Space:
        name = " ".join((name or "").split())
        if not name:
            raise ValidationError("Le nom de l'espace est obligatoire.")
        if self.by_name(name):
            raise ValidationError(f"L'espace « {name} » existe déjà.")
        with self.db.transaction() as c:
            pos = c.execute("SELECT COALESCE(MAX(position),-1)+1 FROM spaces").fetchone()[0]
            cur = c.execute("INSERT INTO spaces(name,icon,color,kind,position) VALUES (?,?,?,?,?)",
                            (name, (icon or "✔").strip()[:4], color, kind, pos))
        self._notify()
        return self.get(cur.lastrowid)

    def update(self, space_id: int, name: str, icon: str, color: str) -> None:
        name = " ".join((name or "").split())
        if not name:
            raise ValidationError("Le nom de l'espace est obligatoire.")
        other = self.by_name(name)
        if other and other.id != space_id:
            raise ValidationError(f"L'espace « {name} » existe déjà.")
        with self.db.transaction() as c:
            c.execute("UPDATE spaces SET name=?, icon=?, color=? WHERE id=?", (name, (icon or "✔").strip()[:4], color, space_id))
        self._notify()

    def set_enabled(self, space_id: int, enabled: bool) -> None:
        if not enabled and len(self.list(enabled_only=True)) <= 1 and self.get(space_id).enabled:
            raise ValidationError("Au moins un espace doit rester actif.")
        with self.db.transaction() as c:
            c.execute("UPDATE spaces SET enabled=? WHERE id=?", (1 if enabled else 0, space_id))
        self._notify()

    def delete(self, space_id: int) -> None:
        n = self.db.conn.execute("SELECT COUNT(*) FROM tasks WHERE space_id=?", (space_id,)).fetchone()[0]
        p = self.db.conn.execute("SELECT COUNT(*) FROM projects WHERE space_id=?", (space_id,)).fetchone()[0]
        if n or p:
            raise ValidationError(f"Cet espace contient {p} projet(s) et {n} tâche(s) : désactivez-le plutôt que de le supprimer.")
        if len(self.list()) <= 1:
            raise ValidationError("Impossible de supprimer le dernier espace.")
        with self.db.transaction() as c:
            c.execute("DELETE FROM spaces WHERE id=?", (space_id,))
        self._notify()
