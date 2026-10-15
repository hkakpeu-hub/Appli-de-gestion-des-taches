"""Fenêtre de création / modification d'une tâche (détails, planification, commentaires, historique)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QHeaderView, QAbstractItemView,
)

from ..core.models import PRIORITIES, PRIORITY_LABELS, KIND_DONE, TaskInput
from ..core.tasks import EVENT_LABELS
from .common import OptDate, OptTime, fmt_dt, show_error


class TaskDialog(QDialog):
    def __init__(self, ctx, task_id: Optional[int] = None, defaults: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.task_id = task_id
        self.saved_id: Optional[int] = None
        self.setWindowTitle("Nouvelle tâche" if task_id is None else f"Tâche #{task_id}")
        self.resize(760, 640)
        self.task = ctx.tasks.get(task_id) if task_id else None

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_details()
        if self.task:
            self._build_comments()
            self._build_history()

        btns = QHBoxLayout()
        self.done_btn = QPushButton("✔ Marquer terminée")
        self.done_btn.clicked.connect(self._mark_done)
        self.done_btn.setVisible(bool(self.task) and self.task.status_kind != KIND_DONE)
        btns.addWidget(self.done_btn)
        btns.addStretch()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("Enregistrer")
        self.save_btn.setObjectName("primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(self.save_btn)
        root.addLayout(btns)
        self._load(defaults or {})

    # ------------------------------------------------------------------ onglet Détails
    def _build_details(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Que faut-il faire ?")
        self.project = QComboBox(); self.project.setEditable(True)
        self.project.lineEdit().setPlaceholderText("Aucun projet")
        self.description = QPlainTextEdit(); self.description.setFixedHeight(90)
        self.assignee = QComboBox(); self.assignee.setEditable(True)
        self.status = QComboBox()
        self.priority = QComboBox()
        self.start_date = OptDate("Début prévu")
        self.deadline = OptDate("Deadline")
        self.start_time = OptTime(); self.end_time = OptTime()
        self.completed = OptDate("Réalisée le")
        self.est = QSpinBox(); self.est.setRange(0, 100000); self.est.setSpecialValueText("—"); self.est.setSuffix(" min")
        self.actual = QSpinBox(); self.actual.setRange(0, 100000); self.actual.setSpecialValueText("—"); self.actual.setSuffix(" min")
        form.addRow("Intitulé *", self.title)
        form.addRow("Projet", self.project)
        form.addRow("Description", self.description)
        form.addRow("Responsable", self.assignee)
        row = QHBoxLayout(); row.addWidget(self.status, 1); row.addWidget(self.priority, 1)
        form.addRow("Statut / priorité", row)
        form.addRow("Dates", self._h(self.start_date, self.deadline))
        form.addRow("Horaires (facultatif)", self._h(QLabel("de"), self.start_time, QLabel("à"), self.end_time))
        form.addRow("Durées", self._h(QLabel("estimée"), self.est, QLabel("réelle"), self.actual))
        form.addRow("Clôture", self.completed)
        self.info = QLabel(); self.info.setObjectName("muted")
        form.addRow("", self.info)
        self.tabs.addTab(page, "Détails")

        for p in self.ctx.projects.list(include_archived=False):
            self.project.addItem(p.name)
        self.project.setCurrentIndex(-1)
        self.assignee.addItems(self.ctx.tasks.assignees())
        self.assignee.setCurrentIndex(-1)
        for s in self.ctx.statuses.list():
            self.status.addItem(s.label, s.id)
        for p in PRIORITIES:
            self.priority.addItem(PRIORITY_LABELS[p], p)
        self.priority.setCurrentIndex(PRIORITIES.index("normal"))

    @staticmethod
    def _h(*widgets) -> QWidget:
        w = QWidget(); lay = QHBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            lay.addWidget(x, 1 if not isinstance(x, QLabel) else 0)
        return w

    def _load(self, defaults: dict) -> None:
        t = self.task
        if t:
            self.title.setText(t.title)
            self.project.setCurrentText(t.project_name)
            self.description.setPlainText(t.description)
            self.assignee.setCurrentText(t.assignee)
            self.status.setCurrentIndex(max(0, self.status.findData(t.status_id)))
            self.priority.setCurrentIndex(PRIORITIES.index(t.priority))
            self.start_date.set_value(t.start_date); self.deadline.set_value(t.deadline)
            self.start_time.set_value(t.start_time); self.end_time.set_value(t.end_time)
            self.completed.set_value(t.completed_at.date() if t.completed_at else None)
            self.est.setValue(t.est_minutes or 0); self.actual.setValue(t.actual_minutes or 0)
            self.info.setText(f"Créée le {fmt_dt(t.created_at)} · modifiée le {fmt_dt(t.updated_at)} · source : {t.source or 'saisie'}")
            self.title.setFocus()
        else:
            self.title.setText(defaults.get("title", ""))
            if defaults.get("project"):
                self.project.setCurrentText(defaults["project"])
            self.assignee.setCurrentText(defaults.get("assignee", self.ctx.settings.get("assignee_default")))
            self.deadline.set_value(defaults.get("deadline"))
            self.start_date.set_value(defaults.get("start_date"))
            self.start_time.set_value(defaults.get("start_time"))
            self.end_time.set_value(defaults.get("end_time"))
            self.title.setFocus()

    def _collect(self) -> TaskInput:
        done_day = self.completed.value()
        done_at = datetime.combine(done_day, datetime.min.time()) if done_day else None
        if self.task and self.task.completed_at and done_day == self.task.completed_at.date():
            done_at = self.task.completed_at  # inchangé : on garde l'heure exacte
        return TaskInput(
            title=self.title.text(), project_name=self.project.currentText(),
            description=self.description.toPlainText(), assignee=self.assignee.currentText(),
            start_date=self.start_date.value(), deadline=self.deadline.value(),
            status_id=self.status.currentData(), priority=self.priority.currentData(),
            start_time=self.start_time.value(), end_time=self.end_time.value(),
            est_minutes=self.est.value() or None, actual_minutes=self.actual.value() or None,
            completed_at=done_at,
            extra_date=self.task.extra_date if self.task else None,
            source="Saisie manuelle" if not self.task else self.task.source,
        )

    def _save(self) -> None:
        try:
            data = self._collect()
            if self.task:
                t = self.ctx.tasks.update(self.task.id, data)
            else:
                t = self.ctx.tasks.create(data)
                note = self.new_comment.toPlainText().strip() if hasattr(self, "new_comment") else ""
                if note:
                    self.ctx.tasks.add_comment(t.id, note)
        except Exception as exc:
            show_error(self, exc, "Enregistrement impossible")
            return
        self.saved_id = t.id
        self.accept()

    def _mark_done(self) -> None:
        self.status.setCurrentIndex(self.status.findData(self.ctx.statuses.first_of_kind(KIND_DONE).id))
        self._save()

    # ------------------------------------------------------------ onglet Commentaires
    def _build_comments(self) -> None:
        page = QWidget(); lay = QVBoxLayout(page)
        self.comment_list = QListWidget()
        self.comment_list.setWordWrap(True)
        self.comment_list.setSelectionMode(QAbstractItemView.NoSelection)
        lay.addWidget(self.comment_list, 1)
        self.new_comment = QPlainTextEdit(); self.new_comment.setFixedHeight(70)
        self.new_comment.setPlaceholderText("Ajouter un commentaire daté (difficulté, décision, point d'avancement…)")
        lay.addWidget(self.new_comment)
        add = QPushButton("Ajouter le commentaire")
        add.clicked.connect(self._add_comment)
        lay.addWidget(add, 0, Qt.AlignRight)
        self.tabs.addTab(page, "Commentaires")
        self._refresh_comments()

    def _refresh_comments(self) -> None:
        self.comment_list.clear()
        for c in self.ctx.tasks.comments(self.task.id):
            item = QListWidgetItem(f"{c.created_at:%d/%m/%Y %H:%M}\n{c.body}")
            self.comment_list.addItem(item)

    def _add_comment(self) -> None:
        try:
            self.ctx.tasks.add_comment(self.task.id, self.new_comment.toPlainText())
        except Exception as exc:
            return show_error(self, exc)
        self.new_comment.clear()
        self._refresh_comments()
        self._refresh_history()

    # ------------------------------------------------------------- onglet Historique
    def _build_history(self) -> None:
        self.hist = QTableWidget(0, 5)
        self.hist.setHorizontalHeaderLabels(["Date", "Événement", "Champ", "Avant", "Après"])
        self.hist.verticalHeader().setVisible(False)
        self.hist.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hist.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.hist.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.hist, "Historique")
        self._refresh_history()

    def _refresh_history(self) -> None:
        events = self.ctx.tasks.history(self.task.id)
        self.hist.setRowCount(len(events))
        for r, e in enumerate(events):
            for c, v in enumerate([fmt_dt(e.at), EVENT_LABELS.get(e.event, e.event), e.field, e.old_value, e.new_value]):
                self.hist.setItem(r, c, QTableWidgetItem(v))
