"""Page Projets : statistiques par projet, création, renommage, archivage."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QHBoxLayout, QHeaderView, QInputDialog, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QLabel,
)
from PySide6.QtGui import QColor

from ..core import metrics
from .common import Page, confirm, page_header, show_error


class ProjectsPage(Page):
    open_project = Signal(int)

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        header, hrow, _ = page_header("Projets", "Double-cliquez sur un projet pour voir toutes ses tâches.")
        add = QPushButton("＋ Nouveau projet"); add.setObjectName("primary"); add.clicked.connect(self.add_project)
        hrow.addWidget(add)
        root.addWidget(header)

        self.show_archived = QCheckBox("Afficher les projets archivés")
        self.show_archived.toggled.connect(self.refresh)
        root.addWidget(self.show_archived)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Projet", "Actions", "Ouvertes", "En retard", "Bloquées", "Terminées", "Avancement", "Indice de charge"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(lambda r, c: self._open(r))
        root.addWidget(self.table, 1)

        foot = QHBoxLayout()
        for label, fn, name in (("Ouvrir les tâches", lambda: self._open(self.table.currentRow()), ""),
                                ("Renommer…", self.rename, ""), ("Couleur…", self.recolor, ""),
                                ("Archiver / désarchiver", self.toggle_archive, ""), ("Supprimer…", self.delete, "danger")):
            b = QPushButton(label); b.clicked.connect(fn)
            if name:
                b.setObjectName(name)
            foot.addWidget(b)
        foot.addStretch()
        root.addLayout(foot)
        self._ids: list[int] = []

    def refresh(self) -> None:
        projects = self.ctx.projects.list(include_archived=self.show_archived.isChecked())
        stats = {s.name: s for s in metrics.project_stats(self.ctx.tasks.all(), self.ctx.clock().date())}
        self._ids = [p.id for p in projects]
        self.table.setRowCount(len(projects))
        for r, p in enumerate(projects):
            s = stats.get(p.name)
            vals = [p.name + ("  (archivé)" if p.archived else ""),
                    s.total if s else 0, s.active if s else 0, s.overdue if s else 0, s.blocked if s else 0,
                    s.done if s else 0, f"{s.done_ratio:.0%}" if s else "—", f"{s.score:g}" if s else "0"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c:
                    it.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    it.setForeground(QColor(p.color or "#334155"))
                    f = it.font(); f.setBold(True); it.setFont(f)
                if c == 3 and s and s.overdue:
                    it.setForeground(QColor("#DC2626"))
                self.table.setItem(r, c, it)

    def _current(self):
        r = self.table.currentRow()
        return self.ctx.projects.get(self._ids[r]) if 0 <= r < len(self._ids) else None

    def _open(self, row: int) -> None:
        if 0 <= row < len(self._ids):
            self.open_project.emit(self._ids[row])

    def add_project(self) -> None:
        name, ok = QInputDialog.getText(self, "Nouveau projet", "Nom du projet :")
        if ok:
            try:
                self.ctx.projects.create(name)
            except Exception as exc:
                return show_error(self, exc)
            self.refresh()

    def rename(self) -> None:
        p = self._current()
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Renommer le projet", "Nouveau nom :", text=p.name)
        if ok:
            try:
                self.ctx.projects.update(p.id, name, p.color, p.description, p.archived)
                self.ctx.tasks.notify_changed()
            except Exception as exc:
                show_error(self, exc)

    def recolor(self) -> None:
        p = self._current()
        if not p:
            return
        c = QColorDialog.getColor(QColor(p.color or "#2563EB"), self, "Couleur du projet")
        if c.isValid():
            self.ctx.projects.update(p.id, p.name, c.name(), p.description, p.archived)
            self.ctx.tasks.notify_changed()

    def toggle_archive(self) -> None:
        p = self._current()
        if p:
            self.ctx.projects.update(p.id, p.name, p.color, p.description, not p.archived)
            self.ctx.tasks.notify_changed()

    def delete(self) -> None:
        p = self._current()
        if p and confirm(self, "Supprimer le projet", f"Supprimer définitivement le projet « {p.name} » ?\n"
                         "(Possible uniquement s'il ne contient aucune tâche.)", "Supprimer", danger=True):
            try:
                self.ctx.projects.delete(p.id)
            except Exception as exc:
                return show_error(self, exc)
            self.refresh()
