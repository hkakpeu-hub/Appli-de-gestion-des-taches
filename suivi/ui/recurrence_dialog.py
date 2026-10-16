"""Création / gestion des tâches répétitives."""
from __future__ import annotations

from datetime import date, time
from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core.models import PRIORITIES, PRIORITY_LABELS
from ..core.recurrence import FREQ_LABELS, WEEKDAYS, RecurrenceInput, describe
from .common import OptDate, OptTime, confirm, fmt_day, show_error


class RecurrenceDialog(QDialog):
    def __init__(self, ctx, series_id: Optional[int] = None, defaults: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.series_id = series_id
        self.setWindowTitle("Nouvelle tâche répétitive" if series_id is None else "Modifier la répétition")
        self.resize(640, 700)
        series = ctx.recurrences.get(series_id) if series_id else None
        defaults = defaults or {}

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.title = QLineEdit(); self.title.setPlaceholderText("Ex. : Culte")
        self.project = QComboBox(); self.project.setEditable(True); self.project.lineEdit().setPlaceholderText("Aucun projet")
        for p in ctx.projects.list(include_archived=False):
            self.project.addItem(p.name)
        self.project.setCurrentIndex(-1)
        self.assignee = QLineEdit()
        self.priority = QComboBox()
        for p in PRIORITIES:
            self.priority.addItem(PRIORITY_LABELS[p], p)
        self.priority.setCurrentIndex(PRIORITIES.index("normal"))
        self.start_time = OptTime(); self.end_time = OptTime()
        self.description = QPlainTextEdit(); self.description.setFixedHeight(60)
        form.addRow("Intitulé *", self.title)
        form.addRow("Projet", self.project)
        form.addRow("Responsable", self.assignee)
        form.addRow("Priorité", self.priority)
        hrow = QWidget(); hl = QHBoxLayout(hrow); hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(QLabel("de")); hl.addWidget(self.start_time, 1); hl.addWidget(QLabel("à")); hl.addWidget(self.end_time, 1)
        form.addRow("Horaires", hrow)
        form.addRow("Description", self.description)
        root.addLayout(form)

        # --- règle de répétition
        box = QVBoxLayout()
        title = QLabel("Répétition"); title.setObjectName("sectionTitle"); box.addWidget(title)
        row = QHBoxLayout()
        row.addWidget(QLabel("Répéter"))
        self.freq = QComboBox()
        for k, v in FREQ_LABELS.items():
            self.freq.addItem(v, k)
        self.freq.setCurrentIndex(1)
        self.interval = QSpinBox(); self.interval.setRange(1, 365); self.interval.setPrefix("tous les "); self.interval.setSuffix(" (intervalle)")
        row.addWidget(self.freq); row.addWidget(self.interval); row.addStretch()
        box.addLayout(row)
        self.days_w = QWidget(); dl = QHBoxLayout(self.days_w); dl.setContentsMargins(0, 0, 0, 0)
        self.day_checks = []
        for i, name in enumerate(WEEKDAYS):
            cb = QCheckBox(name[:3].capitalize()); cb.setToolTip(name.capitalize()); self.day_checks.append(cb); dl.addWidget(cb)
            cb.toggled.connect(self._preview)
        box.addWidget(self.days_w)
        self.mday_w = QWidget(); ml = QHBoxLayout(self.mday_w); ml.setContentsMargins(0, 0, 0, 0)
        self.month_day = QSpinBox(); self.month_day.setRange(1, 31); self.month_day.setPrefix("le ")
        self.month_day.setToolTip("Si le mois est plus court, le dernier jour du mois est utilisé.")
        ml.addWidget(QLabel("Jour du mois :")); ml.addWidget(self.month_day); ml.addStretch()
        box.addWidget(self.mday_w)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("À partir du"))
        self.start_date = QDateEdit(QDate.currentDate()); self.start_date.setCalendarPopup(True); self.start_date.setDisplayFormat("dd/MM/yyyy")
        srow.addWidget(self.start_date); srow.addStretch()
        box.addLayout(srow)
        erow = QHBoxLayout()
        self.end_never = QRadioButton("Sans fin"); self.end_never.setChecked(True)
        self.end_on = QRadioButton("Jusqu'au")
        self.end_date = QDateEdit(QDate.currentDate().addMonths(6)); self.end_date.setCalendarPopup(True); self.end_date.setDisplayFormat("dd/MM/yyyy")
        self.end_after = QRadioButton("Après")
        self.end_count = QSpinBox(); self.end_count.setRange(1, 1000); self.end_count.setValue(10); self.end_count.setSuffix(" occurrences")
        for w in (self.end_never, self.end_on, self.end_date, self.end_after, self.end_count):
            erow.addWidget(w)
        erow.addStretch()
        box.addLayout(erow)
        self.auto_close = QCheckBox("Événement : considérer chaque occurrence comme faite une fois passée "
                                    "(évite les retards pour un culte, une réunion…)")
        self.auto_close.setChecked(True)
        box.addWidget(self.auto_close)
        root.addLayout(box)

        self.summary = QLabel(); self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background:#EEF4FF;border:1px solid #BFD3FF;border-radius:8px;padding:10px;")
        root.addWidget(self.summary)
        root.addStretch()
        btns = QHBoxLayout(); btns.addStretch()
        cancel = QPushButton("Annuler"); cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("Enregistrer"); self.save_btn.setObjectName("primary"); self.save_btn.clicked.connect(self._save)
        btns.addWidget(cancel); btns.addWidget(self.save_btn)
        root.addLayout(btns)

        for w in (self.freq, self.interval, self.month_day, self.start_date, self.end_date, self.end_count):
            (w.currentIndexChanged if isinstance(w, QComboBox) else w.valueChanged if isinstance(w, QSpinBox) else w.dateChanged).connect(self._preview)
        for w in (self.end_never, self.end_on, self.end_after):
            w.toggled.connect(self._preview)
        self.start_time.changed.connect(self._preview); self.end_time.changed.connect(self._preview)
        self.freq.currentIndexChanged.connect(self._sync_fields)

        if series:
            self._load(series)
        else:
            start = defaults.get("start_date") or date.today()
            self.start_date.setDate(QDate(start.year, start.month, start.day))
            self.day_checks[start.weekday()].setChecked(True)
            self.month_day.setValue(start.day)
            self.title.setText(defaults.get("title", ""))
            if defaults.get("start_time"):
                self.start_time.set_value(defaults["start_time"])
            if defaults.get("end_time"):
                self.end_time.set_value(defaults["end_time"])
            self.assignee.setText(ctx.settings.get("assignee_default"))
        self._sync_fields()
        self._preview()
        self.title.setFocus()

    # ---------------------------------------------------------------------------------
    def _load(self, s) -> None:
        self.title.setText(s.title); self.project.setCurrentText(s.project_name); self.assignee.setText(s.assignee)
        self.description.setPlainText(s.description)
        self.priority.setCurrentIndex(PRIORITIES.index(s.priority))
        self.start_time.set_value(s.start_time); self.end_time.set_value(s.end_time)
        self.freq.setCurrentIndex(self.freq.findData(s.freq)); self.interval.setValue(s.interval)
        for i, cb in enumerate(self.day_checks):
            cb.setChecked(i in s.weekdays)
        self.month_day.setValue(s.month_day or (s.start_date.day if s.start_date else 1))
        self.start_date.setDate(QDate(s.start_date.year, s.start_date.month, s.start_date.day))
        if s.end_date:
            self.end_on.setChecked(True); self.end_date.setDate(QDate(s.end_date.year, s.end_date.month, s.end_date.day))
        elif s.count:
            self.end_after.setChecked(True); self.end_count.setValue(s.count)
        self.auto_close.setChecked(s.auto_close)

    def _sync_fields(self) -> None:
        f = self.freq.currentData()
        self.days_w.setVisible(f == "weekly")
        self.mday_w.setVisible(f == "monthly")
        self.interval.setSuffix({"daily": " jour(s)", "weekly": " semaine(s)", "monthly": " mois"}[f])

    def _input(self) -> RecurrenceInput:
        return RecurrenceInput(
            title=self.title.text(), project_name=self.project.currentText(), description=self.description.toPlainText(),
            assignee=self.assignee.text(), priority=self.priority.currentData(),
            start_time=self.start_time.value(), end_time=self.end_time.value(),
            freq=self.freq.currentData(), interval=self.interval.value(),
            weekdays=[i for i, cb in enumerate(self.day_checks) if cb.isChecked()],
            month_day=self.month_day.value() if self.freq.currentData() == "monthly" else None,
            start_date=self.start_date.date().toPython(),
            end_date=self.end_date.date().toPython() if self.end_on.isChecked() else None,
            count=self.end_count.value() if self.end_after.isChecked() else None,
            auto_close=self.auto_close.isChecked(),
        )

    def _preview(self, *_) -> None:
        d = self._input()
        try:
            self.ctx.recurrences.validate(RecurrenceInput(**{**d.__dict__, "title": d.title or "x"}))
        except Exception as exc:
            self.summary.setText(f"⚠ {exc}")
            return
        dates = self.ctx.recurrences.next_dates(d, 5, frm=d.start_date)
        self.summary.setText(describe(d) + "\nProchaines occurrences : " + ", ".join(fmt_day(x) for x in dates))

    def _save(self) -> None:
        try:
            if self.series_id:
                self.ctx.recurrences.update(self.series_id, self._input())
            else:
                self.ctx.recurrences.create(self._input())
        except Exception as exc:
            return show_error(self, exc, "Enregistrement impossible")
        self.accept()


class RecurrenceManager(QDialog):
    """Liste des tâches répétitives de l'espace : modifier, arrêter, supprimer."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Tâches répétitives")
        self.resize(820, 420)
        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Tâche", "Répétition", "Prochaine occurrence"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents); h.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit())
        root.addWidget(self.table, 1)
        row = QHBoxLayout()
        for label, fn, name in (("＋ Nouvelle…", self.add, "primary"), ("Modifier…", self.edit, ""),
                                ("Arrêter la série…", self.stop, ""), ("Supprimer…", self.delete, "danger")):
            b = QPushButton(label); b.clicked.connect(fn)
            if name:
                b.setObjectName(name)
            row.addWidget(b)
        row.addStretch()
        close = QPushButton("Fermer"); close.clicked.connect(self.accept); row.addWidget(close)
        root.addLayout(row)
        self._series = []
        self.refresh()

    def refresh(self) -> None:
        self._series = self.ctx.recurrences.list()
        self.table.setRowCount(len(self._series))
        for r, s in enumerate(self._series):
            nxt = self.ctx.recurrences.next_dates(s, 1)
            for c, v in enumerate([s.title, describe(s), fmt_day(nxt[0]) if nxt else "terminée"]):
                self.table.setItem(r, c, QTableWidgetItem(v))

    def _cur(self):
        r = self.table.currentRow()
        return self._series[r] if 0 <= r < len(self._series) else None

    def add(self) -> None:
        if RecurrenceDialog(self.ctx, None, None, self).exec():
            self.refresh()

    def edit(self) -> None:
        s = self._cur()
        if s and RecurrenceDialog(self.ctx, s.id, None, self).exec():
            self.refresh()

    def stop(self) -> None:
        s = self._cur()
        if s and confirm(self, "Arrêter la série", f"Arrêter « {s.title} » ?\n\nLes occurrences à venir encore intactes seront "
                         "supprimées ; celles déjà passées ou traitées sont conservées.", "Arrêter"):
            n = self.ctx.recurrences.stop(s.id)
            self.refresh()
            QMessageBox.information(self, "Série arrêtée", f"{n} occurrence(s) à venir supprimée(s).")

    def delete(self) -> None:
        s = self._cur()
        if s and confirm(self, "Supprimer la série", f"Supprimer la série « {s.title} » ?\n\nLes occurrences à venir intactes sont "
                         "supprimées ; les autres restent comme tâches ordinaires.", "Supprimer", danger=True):
            self.ctx.recurrences.delete(s.id)
            self.refresh()
