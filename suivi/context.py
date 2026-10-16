"""Conteneur applicatif : assemble base, services métier, alertes, sauvegardes.

Aucune dépendance à Qt ici : l'interface (``suivi.ui``) et la future couche IA (``suivi.ai``)
consomment ce conteneur.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import paths
from .core.alerts import AlertEngine
from .core.attachments import AttachmentService
from .core.spaces import Scope, SpaceService
from .core.backup import BackupService
from .core.projects import ProjectService
from .core.recurrence import RecurrenceService
from .core.settings import Settings
from .core.statuses import StatusService
from .core.tasks import TaskService
from .db import Database
from .excel.importer import ExcelImporter


class AppContext:
    def __init__(self, db_file: Optional[Path] = None, backup_dir: Optional[Path] = None,
                 clock: Callable[[], datetime] = datetime.now):
        self.clock = clock
        self.db = Database(db_file or paths.db_path())
        self.settings = Settings(self.db)
        self.statuses = StatusService(self.db)
        self.spaces = SpaceService(self.db)
        first = next(iter(self.spaces.list(enabled_only=True)), None)
        self.scope = Scope(first.id if first else 1)  # espace affiché
        self.projects = ProjectService(self.db, self.scope)
        self.tasks = TaskService(self.db, self.projects, self.statuses, clock, self.scope)
        self.attachments = AttachmentService(self.db, self.settings, self.tasks, clock)
        self.recurrences = RecurrenceService(self.db, self.tasks, self.projects, self.statuses, self.scope, clock)
        self.alerts = AlertEngine(self.db, self.tasks, self.settings)
        self.backups = BackupService(self.db, self.settings, backup_dir or paths.backups_dir(), clock)
        self.importer = ExcelImporter(self.tasks, backup=lambda: self.backups.create("import"))

    def set_space(self, space_id) -> None:
        """Change l'espace affiché (None = tous). Les pages se rafraîchissent via les abonnements."""
        self.scope.set(space_id)
        self.tasks.notify_changed()

    def restore_backup(self, path: Path) -> Path:
        safety = self.backups.restore(path)
        self.tasks.notify_changed()
        self.alerts._notify()
        return safety

    def close(self) -> None:
        self.db.close()
