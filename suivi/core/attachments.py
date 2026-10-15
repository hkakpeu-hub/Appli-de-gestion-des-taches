"""Pièces jointes : les fichiers vivent sur le disque (jamais dans la base, qui ne contient que le chemin).

Deux modes :
 - **copie** (par défaut) : le fichier est copié dans le dossier des pièces jointes
   ``<dossier>/<espace>/<n° tâche - intitulé>/<fichier>``. Le chemin est stocké *relatif* à ce dossier :
   on peut le déplacer (voir ``change_base``) sans casser les liens ;
 - **lien** : le fichier reste où il est, son chemin absolu est mémorisé.
"""
from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .. import paths
from ..db import Database
from .models import Attachment, ValidationError, iso_datetime, to_datetime
from .settings import Settings
from .tasks import TaskService

log = logging.getLogger(__name__)
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text: str, maxlen: int = 60) -> str:
    s = _INVALID.sub("_", " ".join((text or "").split())).strip(" .")
    return (s[:maxlen].rstrip(" .")) or "sans titre"


class AttachmentService:
    def __init__(self, db: Database, settings: Settings, tasks: TaskService, clock: Callable[[], datetime] = datetime.now):
        self.db, self.settings, self.tasks, self.clock = db, settings, tasks, clock

    # ---------------------------------------------------------------- emplacements
    def base_dir(self) -> Path:
        custom = (self.settings.get("attachments_dir") or "").strip()
        p = Path(custom) if custom else paths.data_dir() / "pieces_jointes"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolve(self, att: Attachment) -> Path:
        p = Path(att.path)
        return (self.base_dir() / p) if att.is_relative else p

    def exists(self, att: Attachment) -> bool:
        return self.resolve(att).is_file()

    # ---------------------------------------------------------------- lecture
    @staticmethod
    def _row(r) -> Attachment:
        return Attachment(r["id"], r["task_id"], r["display_name"], r["path"], bool(r["is_relative"]), r["size"],
                          to_datetime(r["created_at"]))

    def list(self, task_id: int) -> list[Attachment]:
        rows = self.db.conn.execute("SELECT * FROM attachments WHERE task_id=? ORDER BY created_at, id", (task_id,))
        return [self._row(r) for r in rows]

    def get(self, att_id: int) -> Attachment:
        r = self.db.conn.execute("SELECT * FROM attachments WHERE id=?", (att_id,)).fetchone()
        if r is None:
            raise ValidationError("Pièce jointe introuvable.")
        return self._row(r)

    # ---------------------------------------------------------------- écriture
    def add(self, task_id: int, source: Path | str, copy: bool = True) -> Attachment:
        source = Path(source)
        if not source.is_file():
            raise ValidationError(f"Fichier introuvable : {source}")
        task = self.tasks.get(task_id)
        if copy:
            space = self.db.conn.execute("SELECT name FROM spaces WHERE id=?", (task.space_id,)).fetchone()
            folder = Path(safe_name(space["name"] if space else "Espace")) / f"{task.id} - {safe_name(task.title, 50)}"
            dest_dir = self.base_dir() / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / safe_name(source.name, 120)
            n = 2
            while dest.exists():  # ne jamais écraser un fichier existant
                dest = dest_dir / f"{Path(safe_name(source.name, 110)).stem} ({n}){source.suffix}"
                n += 1
            try:
                shutil.copy2(source, dest)
            except OSError as exc:
                raise ValidationError(f"Copie impossible : {exc}") from exc
            stored, relative = str((folder / dest.name).as_posix()), 1
        else:
            stored, relative = str(source.resolve()), 0
        now = self.clock()
        with self.db.transaction() as c:
            cur = c.execute(
                "INSERT INTO attachments(task_id,display_name,path,is_relative,size,created_at) VALUES (?,?,?,?,?,?)",
                (task_id, source.name, stored, relative, source.stat().st_size, iso_datetime(now)))
            c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (iso_datetime(now), task_id))
            self.tasks._history(c, task_id, task.title, "updated", "Pièce jointe", "", source.name, now)
        self.tasks.notify_changed()
        return self.get(cur.lastrowid)

    def remove(self, att_id: int, delete_file: bool = False) -> None:
        """Retire la pièce jointe de la tâche ; ``delete_file`` efface aussi la copie stockée (jamais un fichier lié)."""
        att = self.get(att_id)
        task = self.tasks.get(att.task_id)
        path = self.resolve(att)
        with self.db.transaction() as c:
            c.execute("DELETE FROM attachments WHERE id=?", (att_id,))
            self.tasks._history(c, task.id, task.title, "updated", "Pièce jointe", att.display_name, "retirée")
        if delete_file and att.is_relative and path.is_file():
            try:
                path.unlink()
                if not any(path.parent.iterdir()):
                    path.parent.rmdir()
            except OSError:
                log.warning("Suppression du fichier impossible : %s", path.name)
        self.tasks.notify_changed()

    def change_base(self, new_dir: Path | str, move_files: bool = True) -> int:
        """Change le dossier des pièces jointes ; déplace les fichiers copiés si demandé. Retourne le nombre déplacé."""
        new = Path(new_dir)
        new.mkdir(parents=True, exist_ok=True)
        old = self.base_dir()
        moved = 0
        if move_files and old.resolve() != new.resolve():
            for child in old.iterdir():
                target = new / child.name
                if target.exists():  # fusion : on ne remplace jamais un fichier existant
                    for sub in child.rglob("*"):
                        if sub.is_file():
                            dst = target / sub.relative_to(child)
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            if not dst.exists():
                                shutil.move(str(sub), str(dst)); moved += 1
                else:
                    shutil.move(str(child), str(target)); moved += 1
        self.settings.set("attachments_dir", str(new))
        return moved
