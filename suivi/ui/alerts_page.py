"""Centre de notifications : alertes lues / non lues, report, accès direct à la tâche."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ..core.alerts import KIND_LABELS, LEVEL_COLORS, LEVELS
from .common import Page, fmt_date, fmt_dt, page_header
from .task_dialog import TaskDialog


class AlertsPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        header, hrow, self.sub = page_header("Alertes et notifications",
                                             "Les alertes se mettent à jour automatiquement et disparaissent quand la tâche est traitée.")
        root.addWidget(header)

        bar = QHBoxLayout()
        self.show_read = QCheckBox("Afficher aussi les alertes lues")
        self.show_read.toggled.connect(self.refresh)
        bar.addWidget(self.show_read)
        bar.addStretch()
        b_open = QPushButton("Ouvrir la tâche"); b_open.clicked.connect(self._open)
        b_read = QPushButton("Marquer comme lue"); b_read.clicked.connect(self._read)
        b_all = QPushButton("Tout marquer comme lu"); b_all.clicked.connect(self.ctx.alerts.mark_all_read)
        self.b_snooze = QPushButton("Reporter ▾")
        menu = QMenu(self.b_snooze)
        for label, fn in (("Dans 1 heure", lambda: timedelta(hours=1)), ("Dans 3 heures", lambda: timedelta(hours=3)),
                          ("Demain matin (8 h)", self._tomorrow), ("Dans 3 jours", lambda: timedelta(days=3))):
            menu.addAction(label).triggered.connect(lambda _=False, f=fn: self._snooze(f()))
        self.b_snooze.setMenu(menu)
        for b in (b_open, self.b_snooze, b_read, b_all):
            bar.addWidget(b)
        root.addLayout(bar)

        cols = ["Urgence", "Type", "Tâche", "Projet", "Deadline", "Statut", "Détail", "Créée le"]
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setWordWrap(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(lambda *_: self._open())
        root.addWidget(self.table, 1)
        self._alerts = []

    def _tomorrow(self) -> timedelta:
        now = self.ctx.clock()
        target = datetime.combine(now.date() + timedelta(days=1), time(8, 0))
        return target - now

    def refresh(self) -> None:
        now = self.ctx.clock()
        self._alerts = self.ctx.alerts.visible(now, include_read=self.show_read.isChecked())
        unread = sum(1 for a in self._alerts if a.read_at is None)
        self.sub.setText(f"{unread} non lue(s) · {len(self._alerts)} affichée(s)")
        self.table.setRowCount(len(self._alerts))
        for r, a in enumerate(self._alerts):
            vals = [LEVELS[a.level], KIND_LABELS.get(a.kind, a.kind), a.task_title, a.project_name, fmt_date(a.deadline),
                    a.status_label, a.message, fmt_dt(a.created_at)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if a.read_at is None:
                    f = QFont(); f.setBold(True); it.setFont(f)
                else:
                    it.setForeground(QBrush(QColor("#8A94A6")))
                if c == 0:
                    it.setForeground(QBrush(QColor(LEVEL_COLORS[a.level])))
                it.setToolTip(a.message)
                self.table.setItem(r, c, it)

    def _current(self):
        r = self.table.currentRow()
        return self._alerts[r] if 0 <= r < len(self._alerts) else None

    def _open(self) -> None:
        a = self._current()
        if a:
            self.ctx.alerts.mark_read(a.id)
            TaskDialog(self.ctx, a.task_id, None, self).exec()

    def _read(self) -> None:
        a = self._current()
        if a:
            self.ctx.alerts.mark_read(a.id, a.read_at is None)

    def _snooze(self, delta: timedelta) -> None:
        a = self._current()
        if a:
            self.ctx.alerts.snooze(a.id, self.ctx.clock() + delta)
