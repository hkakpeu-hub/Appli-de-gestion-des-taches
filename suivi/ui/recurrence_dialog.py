"""Création / gestion des tâches répétitives et des événements (uniques ou récurrents)."""
from __future__ import annotations

from datetime import date, time
from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QFormLayout,
)

from ..core.events import EventInput
from ..core.models import PRIORITIES, PRIORITY_LABELS, EventTemplate
from ..core.recurrence import FREQ_LABELS, WEEKDAYS, RecurrenceInput, describe
from .common import OptTime, confirm, fmt_day, show_error


class RecurrenceDialog(QDialog):
    """``kind`` = « task » (tâche répétitive) ou « event » (événement : une fois ou récurrent, avec tâches modèles)."""

    def __init__(self, ctx, series_id: Optional[int] = None, defaults: Optional[dict] = None, kind: str = "task", parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.series_id = series_id
        series = ctx.recurrences.get(series_id) if series_id else None
        self.kind = series.kind if series else kind
        ev = self.kind == "event"
        self.setWindowTitle(("Nouvel événement" if ev else "Nouvelle tâche répétitive") if series_id is None
                            else ("Modifier l'événement récurrent" if ev else "Modifier la répétition"))
        self.resize(660, 860 if ev else 720)
        defaults = defaults or {}

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.title = QLineEdit(); self.title.setPlaceholderText("Ex. : Culte" if ev else "Ex. : Rapport hebdomadaire")
        self.project = QComboBox(); self.project.setEditable(True); self.project.lineEdit().setPlaceholderText("Aucun projet")
        for p in ctx.projects.list(include_archived=False):
            self.project.addItem(p.name)
        self.project.setCurrentIndex(-1)
        self.assignee = QLineEdit()
        self.location = QLineEdit(); self.location.setPlaceholderText("Lieu (facultatif)")
        self.priority = QComboBox()
        for p in PRIORITIES:
            self.priority.addItem(PRIORITY_LABELS[p], p)
        self.priority.setCurrentIndex(PRIORITIES.index("normal"))
        self.start_time = OptTime(); self.end_time = OptTime()
        self.description = QPlainTextEdit(); self.description.setFixedHeight(56)
        form.addRow("Intitulé *", self.title)
        if ev:
            form.addRow("Lieu", self.location)
        else:
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
        title = QLabel("Répétition" if not ev else "Date et répétition"); title.setObjectName("sectionTitle"); box.addWidget(title)
        row = QHBoxLayout()
        row.addWidget(QLabel("Fréquence" if ev else "Répéter"))
        self.freq = QComboBox()
        if ev:
            self.freq.addItem("Une seule fois", "once")
        for k, v in FREQ_LABELS.items():
            self.freq.addItem(v, k)
        self.freq.setCurrentIndex(self.freq.findData("weekly"))
        self.interval = QSpinBox(); self.interval.setRange(1, 365); self.interval.setPrefix("tous les ")
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
        self.start_label = QLabel("À partir du")
        srow.addWidget(self.start_label)
        self.start_date = QDateEdit(QDate.currentDate()); self.start_date.setCalendarPopup(True); self.start_date.setDisplayFormat("dd/MM/yyyy")
        srow.addWidget(self.start_date); srow.addStretch()
        box.addLayout(srow)
        self.end_w = QWidget(); erow = QHBoxLayout(self.end_w); erow.setContentsMargins(0, 0, 0, 0)
        self.end_never = QRadioButton("Sans fin"); self.end_never.setChecked(True)
        self.end_on = QRadioButton("Jusqu'au")
        self.end_date = QDateEdit(QDate.currentDate().addMonths(6)); self.end_date.setCalendarPopup(True); self.end_date.setDisplayFormat("dd/MM/yyyy")
        self.end_after = QRadioButton("Après")
        self.end_count = QSpinBox(); self.end_count.setRange(1, 1000); self.end_count.setValue(10); self.end_count.setSuffix(" occurrences")
        for w in (self.end_never, self.end_on, self.end_date, self.end_after, self.end_count):
            erow.addWidget(w)
        erow.addStretch()
        box.addWidget(self.end_w)
        root.addLayout(box)

        # --- tâches modèles (événements)
        self.tpl_box = QWidget()
        tl = QVBoxLayout(self.tpl_box); tl.setContentsMargins(0, 6, 0, 0)
        t_title = QLabel("Tâches à rattacher à chaque occurrence"); t_title.setObjectName("sectionTitle")
        tl.addWidget(t_title)
        hint = QLabel("Ex. pour un culte : Chanter, Danser, Prier, Lecture biblique… Elles sont créées automatiquement "
                      "pour chaque date et rattachées à l'événement.")
        hint.setWordWrap(True); hint.setObjectName("muted")
        tl.addWidget(hint)
        self.tpl = QTableWidget(0, 3)
        self.tpl.setHorizontalHeaderLabels(["Tâche", "Responsable", "Échéance : jours avant"])
        self.tpl.verticalHeader().setVisible(False)
        self.tpl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tpl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tpl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tpl.setMinimumHeight(150)
        tl.addWidget(self.tpl)
        trow = QHBoxLayout()
        b_add = QPushButton("＋ Ajouter une tâche"); b_add.clicked.connect(lambda: self._tpl_add())
        b_del = QPushButton("Retirer"); b_del.clicked.connect(self._tpl_remove)
        trow.addWidget(b_add); trow.addWidget(b_del); trow.addStretch()
        tl.addLayout(trow)
        root.addWidget(self.tpl_box)
        self.tpl_box.setVisible(ev)
        self._tpl_ids: list[Optional[int]] = []

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
            if ev:
                self.freq.setCurrentIndex(self.freq.findData("once"))
        self._sync_fields()
        self._preview()
        self.title.setFocus()

    # ---------------------------------------------------------------------------------
    def _tpl_add(self, title: str = "", assignee: str = "", days: int = 0, tpl_id: Optional[int] = None) -> None:
        r = self.tpl.rowCount()
        self.tpl.insertRow(r)
        self._tpl_ids.append(tpl_id)
        self.tpl.setItem(r, 0, QTableWidgetItem(title))
        self.tpl.setItem(r, 1, QTableWidgetItem(assignee))
        spin = QSpinBox(); spin.setRange(0, 365); spin.setValue(days); spin.setSuffix(" j")
        self.tpl.setCellWidget(r, 2, spin)
        if not title:
            self.tpl.setCurrentCell(r, 0)
            self.tpl.editItem(self.tpl.item(r, 0))

    def _tpl_remove(self) -> None:
        r = self.tpl.currentRow()
        if r >= 0:
            self.tpl.removeRow(r)
            self._tpl_ids.pop(r)

    def _templates(self) -> list[EventTemplate]:
        out = []
        for r in range(self.tpl.rowCount()):
            title = (self.tpl.item(r, 0).text() if self.tpl.item(r, 0) else "").strip()
            if title:
                out.append(EventTemplate(title, (self.tpl.item(r, 1).text() if self.tpl.item(r, 1) else "").strip(),
                                         self.tpl.cellWidget(r, 2).value(), self._tpl_ids[r]))
        return out

    def _load(self, s) -> None:
        if self.freq.findData("once") >= 0:  # une série existante reste une série
            self.freq.removeItem(self.freq.findData("once"))
        self.title.setText(s.title); self.project.setCurrentText(s.project_name); self.assignee.setText(s.assignee)
        self.location.setText(s.location)
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
        self.freq.setEnabled(True)
        for t in self.ctx.recurrences.templates(s.id):
            self._tpl_add(t.title, t.assignee, t.days_before, t.id)

    def _sync_fields(self) -> None:
        f = self.freq.currentData()
        rec = f != "once"
        self.days_w.setVisible(f == "weekly")
        self.mday_w.setVisible(f == "monthly")
        self.interval.setVisible(rec); self.end_w.setVisible(rec)
        self.start_label.setText("À partir du" if rec else "Date")
        if rec:
            self.interval.setSuffix({"daily": " jour(s)", "weekly": " semaine(s)", "monthly": " mois"}[f])

    def _input(self) -> RecurrenceInput:
        f = self.freq.currentData()
        return RecurrenceInput(
            title=self.title.text(), project_name=self.project.currentText(), description=self.description.toPlainText(),
            assignee=self.assignee.text(), priority=self.priority.currentData(),
            start_time=self.start_time.value(), end_time=self.end_time.value(),
            freq=f if f != "once" else "daily", interval=self.interval.value() if f != "once" else 1,
            weekdays=[i for i, cb in enumerate(self.day_checks) if cb.isChecked()],
            month_day=self.month_day.value() if f == "monthly" else None,
            start_date=self.start_date.date().toPython(),
            end_date=self.end_date.date().toPython() if self.end_on.isChecked() and f != "once" else None,
            count=self.end_count.value() if self.end_after.isChecked() and f != "once" else None,
            kind=self.kind, location=self.location.text(), templates=self._templates(),
        )

    def _preview(self, *_) -> None:
        d = self._input()
        if self.freq.currentData() == "once":
            self.summary.setText(f"Le {fmt_day(d.start_date)}" + (f", de {d.start_time:%H:%M}" if d.start_time else "")
                                 + (f" à {d.end_time:%H:%M}" if d.end_time else ""))
            return
        try:
            self.ctx.recurrences.validate(RecurrenceInput(**{**d.__dict__, "title": d.title or "x"}))
        except Exception as exc:
            self.summary.setText(f"⚠ {exc}")
            return
        dates = self.ctx.recurrences.next_dates(d, 5, frm=d.start_date)
        self.summary.setText(describe(d) + "\nProchaines occurrences : " + ", ".join(fmt_day(x) for x in dates))

    def _save(self) -> None:
        try:
            d = self._input()
            if self.freq.currentData() == "once" and not self.series_id:
                self.ctx.events.create(
                    EventInput(d.title, d.start_date, d.start_time, d.end_time, d.location, d.description),
                    new_tasks=[(t.title, t.assignee, t.days_before) for t in d.templates])
            elif self.series_id:
                self.ctx.recurrences.update(self.series_id, d)
            else:
                self.ctx.recurrences.create(d)
        except Exception as exc:
            return show_error(self, exc, "Enregistrement impossible")
        self.accept()


class RecurrenceManager(QDialog):
    """Liste des séries (tâches répétitives et événements récurrents) de l'espace."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Répétitions")
        self.resize(900, 440)
        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Type", "Intitulé", "Répétition", "Prochaine occurrence"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents); h.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit())
        root.addWidget(self.table, 1)
        row = QHBoxLayout()
        for label, fn, name in (("＋ Événement…", lambda: self.add("event"), "primary"), ("＋ Tâche répétitive…", lambda: self.add("task"), ""),
                                ("Modifier…", self.edit, ""), ("Arrêter la série…", self.stop, ""), ("Supprimer…", self.delete, "danger")):
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
            vals = ["🗓 Événement" if s.kind == "event" else "↻ Tâche", s.title, describe(s), fmt_day(nxt[0]) if nxt else "terminée"]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))

    def _cur(self):
        r = self.table.currentRow()
        return self._series[r] if 0 <= r < len(self._series) else None

    def add(self, kind: str) -> None:
        if RecurrenceDialog(self.ctx, None, None, kind, self).exec():
            self.refresh()

    def edit(self) -> None:
        s = self._cur()
        if s and RecurrenceDialog(self.ctx, s.id, None, s.kind, self).exec():
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
                         "supprimées ; les autres restent, détachées de la série.", "Supprimer", danger=True):
            self.ctx.recurrences.delete(s.id)
            self.refresh()
