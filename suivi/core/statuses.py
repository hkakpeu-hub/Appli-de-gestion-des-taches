"""Statuts configurables."""
from __future__ import annotations

from typing import Optional

from ..db import Database
from .models import KINDS, KIND_DONE, Status, ValidationError


class StatusService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _row(r) -> Status:
        return Status(r["id"], r["label"], r["kind"], r["color"], r["position"], bool(r["is_active"]))

    def list(self, include_inactive: bool = False) -> list[Status]:
        sql = "SELECT * FROM statuses" + ("" if include_inactive else " WHERE is_active=1") + " ORDER BY position, id"
        return [self._row(r) for r in self.db.conn.execute(sql)]

    def get(self, status_id: int) -> Status:
        r = self.db.conn.execute("SELECT * FROM statuses WHERE id=?", (status_id,)).fetchone()
        if r is None:
            raise ValidationError("Statut introuvable.")
        return self._row(r)

    def by_label(self, label: str) -> Optional[Status]:
        r = self.db.conn.execute("SELECT * FROM statuses WHERE label=? ", (label.strip(),)).fetchone()
        return self._row(r) if r else None

    def first_of_kind(self, kind: str) -> Status:
        r = self.db.conn.execute(
            "SELECT * FROM statuses WHERE kind=? AND is_active=1 ORDER BY position LIMIT 1", (kind,)
        ).fetchone()
        if r is None:  # statut désactivé : on retombe sur n'importe lequel de cette nature
            r = self.db.conn.execute("SELECT * FROM statuses WHERE kind=? ORDER BY position LIMIT 1", (kind,)).fetchone()
        if r is None:
            raise ValidationError(f"Aucun statut de nature « {KINDS.get(kind, kind)} ».")
        return self._row(r)

    def add(self, label: str, kind: str, color: str = "#64748B") -> Status:
        label = (label or "").strip()
        if not label:
            raise ValidationError("Le libellé du statut est obligatoire.")
        if kind not in KINDS:
            raise ValidationError("Nature de statut inconnue.")
        if self.by_label(label):
            raise ValidationError(f"Le statut « {label} » existe déjà.")
        with self.db.transaction() as c:
            pos = c.execute("SELECT COALESCE(MAX(position),-1)+1 FROM statuses").fetchone()[0]
            cur = c.execute(
                "INSERT INTO statuses(label,kind,color,position) VALUES (?,?,?,?)", (label, kind, color, pos)
            )
        return self.get(cur.lastrowid)

    def update(self, status_id: int, label: str, color: str, is_active: bool = True) -> None:
        label = (label or "").strip()
        if not label:
            raise ValidationError("Le libellé du statut est obligatoire.")
        st = self.get(status_id)
        other = self.by_label(label)
        if other and other.id != status_id:
            raise ValidationError(f"Le statut « {label} » existe déjà.")
        if not is_active:
            remaining = self.db.conn.execute(
                "SELECT COUNT(*) FROM statuses WHERE kind=? AND is_active=1 AND id<>?", (st.kind, status_id)
            ).fetchone()[0]
            if remaining == 0:
                raise ValidationError("Il doit rester au moins un statut actif pour cette nature.")
        with self.db.transaction() as c:
            c.execute(
                "UPDATE statuses SET label=?, color=?, is_active=? WHERE id=?",
                (label, color, 1 if is_active else 0, status_id),
            )

    def delete(self, status_id: int) -> None:
        used = self.db.conn.execute("SELECT COUNT(*) FROM tasks WHERE status_id=?", (status_id,)).fetchone()[0]
        if used:
            raise ValidationError(f"Ce statut est utilisé par {used} tâche(s) : désactivez-le plutôt que de le supprimer.")
        st = self.get(status_id)
        remaining = self.db.conn.execute(
            "SELECT COUNT(*) FROM statuses WHERE kind=? AND id<>?", (st.kind, status_id)
        ).fetchone()[0]
        if remaining == 0:
            raise ValidationError("Impossible de supprimer le dernier statut de cette nature.")
        with self.db.transaction() as c:
            c.execute("DELETE FROM statuses WHERE id=?", (status_id,))

    def done_ids(self) -> list[int]:
        return [s.id for s in self.list(True) if s.kind == KIND_DONE]
