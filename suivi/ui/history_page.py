"""Historique des modifications + corbeille (restauration / suppression définitive)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..core.tasks import EVENT_LABELS
from .common import Page, confirm, fmt_date, fmt_dt, page_header, show_error


class HistoryPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        header, _, self.sub = page_header("Historique", "Toutes les modifications importantes : statuts, deadlines, priorités, commentaires, clôtures.")
        root.addWidget(header)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # --- journal
        page = QWidget(); lay = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.text = QLineEdit(); self.text.setPlaceholderText("🔍 Filtrer par tâche ou valeur…"); self.text.setClearButtonEnabled(True)
        self.event = QComboBox(); self.event.addItem("Tous les événements", "")
        for k, v in EVENT_LABELS.items():
            self.event.addItem(v, k)
        bar.addWidget(self.text, 1); bar.addWidget(self.event)
        lay.addLayout(bar)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Date", "Tâche", "Événement", "Champ", "Avant", "Après"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        lay.addWidget(self.table)
        self.tabs.addTab(page, "Journal des modifications")
        self.text.textChanged.connect(lambda *_: self.refresh())
        self.event.currentIndexChanged.connect(lambda *_: self.refresh())

        # --- corbeille
        page2 = QWidget(); lay2 = QVBoxLayout(page2)
        self.trash = QTableWidget(0, 4)
        self.trash.setHorizontalHeaderLabels(["Tâche", "Projet", "Deadline", "Supprimée le"])
        self.trash.verticalHeader().setVisible(False)
        self.trash.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trash.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trash.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.trash.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay2.addWidget(self.trash)
        row = QHBoxLayout(); row.addStretch()
        b_res = QPushButton("Restaurer"); b_res.clicked.connect(self._restore)
        b_purge = QPushButton("Supprimer définitivement…"); b_purge.setObjectName("danger"); b_purge.clicked.connect(self._purge)
        row.addWidget(b_res); row.addWidget(b_purge)
        lay2.addLayout(row)
        self.tabs.addTab(page2, "Corbeille")
        self._trash_ids: list[int] = []

    def refresh(self) -> None:
        events = self.ctx.tasks.history(None, 1000, self.event.currentData() or "", self.text.text())
        self.table.setRowCount(len(events))
        for r, e in enumerate(events):
            for c, v in enumerate([fmt_dt(e.at), e.task_title, EVENT_LABELS.get(e.event, e.event), e.field, e.old_value, e.new_value]):
                self.table.setItem(r, c, QTableWidgetItem(v))
        deleted = self.ctx.tasks.deleted()
        self._trash_ids = [t.id for t in deleted]
        self.trash.setRowCount(len(deleted))
        for r, t in enumerate(deleted):
            for c, v in enumerate([t.title, t.project_name, fmt_date(t.deadline), fmt_dt(t.deleted_at)]):
                self.trash.setItem(r, c, QTableWidgetItem(v))
        self.tabs.setTabText(1, f"Corbeille ({len(deleted)})")
        self.sub.setText(f"{len(events)} événement(s) affiché(s) (1000 derniers maximum)")

    def _selected(self):
        r = self.trash.currentRow()
        return self._trash_ids[r] if 0 <= r < len(self._trash_ids) else None

    def _restore(self) -> None:
        i = self._selected()
        if i:
            self.ctx.tasks.restore(i)

    def _purge(self) -> None:
        i = self._selected()
        if i and confirm(self, "Suppression définitive",
                         "Cette tâche et ses commentaires seront effacés définitivement.\n"
                         "(Seule une sauvegarde permettrait de les retrouver.)", "Supprimer définitivement", danger=True):
            try:
                self.ctx.backups.create("manuel")
                self.ctx.tasks.purge(i)
            except Exception as exc:
                show_error(self, exc)
