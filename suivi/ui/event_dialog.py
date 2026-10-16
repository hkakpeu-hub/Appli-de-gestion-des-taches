"""Fiche d'un événement : informations, tâches rattachées (avec avancement), rattachement de tâches existantes."""
from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.events import EventInput
from ..core.models import KIND_DONE, KIND_TODO
from ..core.quickadd import parse_quick
from ..core.recurrence import describe
from ..core.tasks import TaskFilter
from . import theme
from .common import OptTime, confirm, fmt_day, show_error
from .task_dialog import TaskDialog


class PickTaskDialog(QDialog):
    """Choix d'une tâche ouverte existante à rattacher à l'événement."""

    def __init__(self, ctx, exclude_event: int, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Rattacher une tâche existante")
        self.resize(560, 480)
        self.chosen: list[int] = []
        lay = QVBoxLayout(self)
        self.search = QLineEdit(); self.search.setPlaceholderText("🔍  Rechercher une tâche ouverte…"); self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        lay.addWidget(self.search)
        self.list = QListWidget(); self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda *_: self._ok())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton("Annuler"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Rattacher"); ok.setObjectName("primary"); ok.clicked.connect(self._ok)
        row.addWidget(cancel); row.addWidget(ok)
        lay.addLayout(row)
        self.exclude = exclude_event
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        tasks = self.ctx.tasks.list(TaskFilter(text=self.search.text(), only_active=True, sort="deadline"))
        for t in tasks[:300]:
            if t.event_id == self.exclude:
                continue
            extra = f" — déjà liée à « {t.event_title} »" if t.event_id else ""
            it = QListWidgetItem(f"{t.title}   ·   {t.project_name or 'sans projet'}   ·   {fmt_day(t.deadline) if t.deadline else 'sans deadline'}{extra}")
            it.setData(Qt.UserRole, t.id)
            self.list.addItem(it)

    def _ok(self) -> None:
        self.chosen = [it.data(Qt.UserRole) for it in self.list.selectedItems()]
        if self.chosen:
            self.accept()


class EventDialog(QDialog):
    def __init__(self, ctx, event_id: Optional[int] = None, defaults: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.event_id = event_id
        self.ev = ctx.events.get(event_id) if event_id else None
        self.setWindowTitle("Événement" if event_id else "Nouvel événement")
        self.resize(780, 720)
        defaults = defaults or {}

        root = QVBoxLayout(self)
        form = QFormLayout(); form.setVerticalSpacing(8)
        self.title = QLineEdit(); self.title.setPlaceholderText("Ex. : Culte")
        self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True); self.date.setDisplayFormat("dd/MM/yyyy")
        self.start_time = OptTime(); self.end_time = OptTime()
        self.location = QLineEdit(); self.location.setPlaceholderText("Lieu (facultatif)")
        self.description = QPlainTextEdit(); self.description.setFixedHeight(54)
        form.addRow("Intitulé *", self.title)
        trow = QWidget(); tl = QHBoxLayout(trow); tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.date); tl.addWidget(QLabel("de")); tl.addWidget(self.start_time, 1); tl.addWidget(QLabel("à")); tl.addWidget(self.end_time, 1)
        form.addRow("Date et horaires", trow)
        form.addRow("Lieu", self.location)
        form.addRow("Description", self.description)
        root.addLayout(form)
        self.series_label = QLabel(); self.series_label.setObjectName("muted"); self.series_label.setWordWrap(True)
        root.addWidget(self.series_label)

        # --- tâches rattachées
        head = QHBoxLayout()
        h = QLabel("Tâches rattachées"); h.setObjectName("sectionTitle")
        self.progress_label = QLabel(); self.progress_label.setObjectName("muted")
        head.addWidget(h); head.addStretch(); head.addWidget(self.progress_label)
        root.addLayout(head)
        self.bar = QProgressBar(); self.bar.setTextVisible(False); self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(f"QProgressBar{{background:#E6EAF1;border-radius:4px;border:none;}}"
                               f"QProgressBar::chunk{{background:{theme.SUCCESS};border-radius:4px;}}")
        root.addWidget(self.bar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["✓", "Tâche", "Responsable", "Échéance"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents); hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents); hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._toggled)
        self.table.cellDoubleClicked.connect(lambda r, c: self._open() if c else None)
        root.addWidget(self.table, 1)
        self.quick = QLineEdit()
        self.quick.setPlaceholderText("＋  Ajouter une tâche liée :  Chanter  @Marie  !+1j   (Entrée)")
        self.quick.returnPressed.connect(self._quick_add)
        root.addWidget(self.quick)
        row = QHBoxLayout()
        for label, fn in (("Rattacher une tâche existante…", self._pick), ("Ouvrir la tâche", self._open), ("Détacher", self._detach)):
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch()
        root.addLayout(row)

        btns = QHBoxLayout()
        self.delete_btn = QPushButton("Supprimer l'événement…"); self.delete_btn.setObjectName("danger"); self.delete_btn.clicked.connect(self._delete)
        self.series_btn = QPushButton("Modifier la série…"); self.series_btn.clicked.connect(self._edit_series)
        btns.addWidget(self.delete_btn); btns.addWidget(self.series_btn); btns.addStretch()
        close = QPushButton("Fermer"); close.clicked.connect(self.reject)
        self.save_btn = QPushButton("Enregistrer"); self.save_btn.setObjectName("primary"); self.save_btn.clicked.connect(self._save)
        btns.addWidget(close); btns.addWidget(self.save_btn)
        root.addLayout(btns)

        self._loading = False
        self._tasks = []
        self._load(defaults)

    # ----------------------------------------------------------------------------------------
    def _load(self, defaults: dict) -> None:
        e = self.ev
        if e:
            self.title.setText(e.title)
            self.date.setDate(QDate(e.date.year, e.date.month, e.date.day))
            self.start_time.set_value(e.start_time); self.end_time.set_value(e.end_time)
            self.location.setText(e.location); self.description.setPlainText(e.description)
            if e.series_id:
                s = self.ctx.recurrences.get(e.series_id)
                self.series_label.setText(f"↻ Fait partie d'une série : {describe(s)}")
        else:
            d = defaults.get("start_date") or date.today()
            self.date.setDate(QDate(d.year, d.month, d.day))
            self.title.setText(defaults.get("title", ""))
            self.start_time.set_value(defaults.get("start_time")); self.end_time.set_value(defaults.get("end_time"))
        has = e is not None
        self.series_btn.setVisible(bool(e and e.series_id))
        self.delete_btn.setVisible(has)
        for w in (self.table, self.quick):
            w.setEnabled(has)
        if not has:
            self.quick.setPlaceholderText("Enregistrez l'événement pour lui rattacher des tâches.")
        self._refresh_tasks()

    def _collect(self) -> EventInput:
        return EventInput(self.title.text(), self.date.date().toPython(), self.start_time.value(), self.end_time.value(),
                          self.location.text(), self.description.toPlainText())

    def _save(self) -> None:
        try:
            if self.ev:
                self.ev = self.ctx.events.update(self.ev.id, self._collect())
            else:
                self.ev = self.ctx.events.create(self._collect())
        except Exception as exc:
            return show_error(self, exc, "Enregistrement impossible")
        self.event_id = self.ev.id
        self.accept()

    # ------------------------------------------------------------------ tâches liées
    def _refresh_tasks(self) -> None:
        self._loading = True
        self._tasks = self.ctx.events.linked_tasks(self.ev.id) if self.ev else []
        self.table.setRowCount(len(self._tasks))
        done = 0
        for r, t in enumerate(self._tasks):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            is_done = t.status_kind == KIND_DONE
            done += is_done
            chk.setCheckState(Qt.Checked if is_done else Qt.Unchecked)
            self.table.setItem(r, 0, chk)
            title = QTableWidgetItem(t.title + ("" if t.status_kind in (KIND_DONE, KIND_TODO) else f"  ({t.status_label})"))
            if is_done:
                f = title.font(); f.setStrikeOut(True); title.setFont(f); title.setForeground(Qt.gray)
            self.table.setItem(r, 1, title)
            self.table.setItem(r, 2, QTableWidgetItem(t.assignee))
            self.table.setItem(r, 3, QTableWidgetItem(fmt_day(t.deadline) if t.deadline else "—"))
        n = len(self._tasks)
        self.progress_label.setText(f"{done} / {n} faite(s)" if n else "aucune tâche rattachée")
        self.bar.setMaximum(max(1, n)); self.bar.setValue(done)
        self._loading = False

    def _toggled(self, item) -> None:
        if self._loading or item.column() != 0:
            return
        t = self._tasks[item.row()]
        try:
            if item.checkState() == Qt.Checked:
                self.ctx.tasks.complete(t.id)
            else:
                self.ctx.tasks.set_status(t.id, self.ctx.statuses.first_of_kind(KIND_TODO).id)
        except Exception as exc:
            show_error(self, exc)
        self._refresh_tasks()

    def _current_task(self):
        r = self.table.currentRow()
        return self._tasks[r] if 0 <= r < len(self._tasks) else None

    def _quick_add(self) -> None:
        text = self.quick.text().strip()
        if not text or not self.ev:
            return
        try:
            data = parse_quick(text, self.ctx.clock().date())
            self.ctx.events.add_task(self.ev.id, data.title, data.assignee, 0, deadline=data.deadline or self.ev.date)
        except Exception as exc:
            return show_error(self, exc, "Ajout impossible")
        self.quick.clear()
        self._refresh_tasks()

    def _pick(self) -> None:
        dlg = PickTaskDialog(self.ctx, self.ev.id, self)
        if dlg.exec():
            try:
                for tid in dlg.chosen:
                    self.ctx.events.link(tid, self.ev.id)
            except Exception as exc:
                show_error(self, exc)
            self._refresh_tasks()

    def _detach(self) -> None:
        t = self._current_task()
        if t:
            self.ctx.events.link(t.id, None)
            self._refresh_tasks()

    def _open(self) -> None:
        t = self._current_task()
        if t:
            TaskDialog(self.ctx, t.id, None, self).exec()
            self._refresh_tasks()

    # ------------------------------------------------------------------ série / suppression
    def _edit_series(self) -> None:
        from .recurrence_dialog import RecurrenceDialog
        if RecurrenceDialog(self.ctx, self.ev.series_id, None, "event", self).exec():
            self.ev = self.ctx.events.get(self.ev.id)
            self._load({})

    def _delete(self) -> None:
        e = self.ev
        box = QMessageBox(QMessageBox.Warning, "Supprimer l'événement", f"Supprimer « {e.title} » du {fmt_day(e.date)} ?"
                          + ("\n\nSeule cette occurrence est supprimée (la série continue)." if e.series_id else ""), parent=self)
        keep = box.addButton("Supprimer (garder les tâches)", QMessageBox.AcceptRole)
        kill = box.addButton("Supprimer l'événement et ses tâches", QMessageBox.DestructiveRole)
        box.addButton("Annuler", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() in (keep, kill):
            self.ctx.events.delete(e.id, delete_tasks=box.clickedButton() is kill)
            self.accept()
