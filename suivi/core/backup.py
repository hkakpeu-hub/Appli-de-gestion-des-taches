"""Sauvegarde et restauration de la base de données."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..db import Database
from .settings import Settings

log = logging.getLogger(__name__)
NAME_RE = re.compile(r"^taches_(\d{8}_\d{6})(?:_([a-z\-]+))?\.db$")
REASONS = {"auto": "Automatique", "manuel": "Manuelle", "import": "Avant import", "restauration": "Avant restauration",
           "fermeture": "À la fermeture"}


@dataclass
class BackupInfo:
    path: Path
    created: datetime
    reason: str
    size: int

    @property
    def reason_label(self) -> str:
        return REASONS.get(self.reason, self.reason or "—")


class BackupService:
    def __init__(self, db: Database, settings: Settings, folder: Path, clock=datetime.now):
        self.db = db
        self.settings = settings
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.clock = clock

    def create(self, reason: str = "manuel", prune: bool = True) -> Path:
        now = self.clock()
        dest = self.folder / f"taches_{now:%Y%m%d_%H%M%S}_{reason}.db"
        while dest.exists():  # deux sauvegardes dans la même seconde : on décale l'horodatage
            now += timedelta(seconds=1)
            dest = self.folder / f"taches_{now:%Y%m%d_%H%M%S}_{reason}.db"
        self.db.backup_to(dest)
        log.info("Sauvegarde créée : %s", dest.name)
        if prune:
            self.prune()
        return dest

    def list(self) -> list[BackupInfo]:
        out = []
        for p in self.folder.glob("taches_*.db"):
            m = NAME_RE.match(p.name)
            if not m:
                continue
            out.append(BackupInfo(p, datetime.strptime(m.group(1), "%Y%m%d_%H%M%S"), m.group(2) or "", p.stat().st_size))
        return sorted(out, key=lambda b: b.created, reverse=True)

    def prune(self) -> int:
        """Ne conserve que les N sauvegardes les plus récentes (les sauvegardes manuelles et pré-restauration
        comptent aussi dans le quota, mais la plus récente est toujours gardée)."""
        keep = max(1, int(self.settings.get("backup_keep")))
        removed = 0
        for b in self.list()[keep:]:
            try:
                b.path.unlink()
                removed += 1
            except OSError:
                log.warning("Impossible de supprimer %s", b.path.name)
        return removed

    def auto_if_due(self) -> Optional[Path]:
        if not self.settings.get("backup_auto"):
            return None
        existing = self.list()
        hours = float(self.settings.get("backup_interval_hours"))
        if existing and (self.clock() - existing[0].created) < timedelta(hours=hours):
            return None
        return self.create("auto")

    def restore(self, path: Path) -> Path:
        """Restaure ``path``. Une sauvegarde de sécurité de l'état courant est faite avant."""
        safety = self.create("restauration", prune=False)
        try:
            self.db.restore_from(path)
        except Exception:
            log.exception("Échec de la restauration, base courante conservée")
            raise
        self.prune()
        return safety
