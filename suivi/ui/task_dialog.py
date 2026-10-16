"""Fenêtre de création / modification d'une tâche (détails, planification, commentaires, historique)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QMessageBox,
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QHeaderView, QAbstractItemView,
)

from ..core.models import PRIORITIES, PRIORITY_LABELS, KIND_DONE, TaskInput
from ..core.tasks import EVENT_LABELS
from .. import osutils
from .common import OptDate, OptTime, confirm, fmt_dt, show_error


ICONS = {".pdf": "📕", ".doc": "📘", ".docx": "📘", ".xls": "📗", ".xlsx": "📗", ".csv": "📗", ".ppt": "📙",
         ".pptx": "📙", ".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼", ".gif": "🖼", ".webp": "🖼", ".zip": "🗜",
         ".txt": "📄", ".msg": "✉", ".eml": "✉"}


class DropList(QListWidget):
    """Liste qui accepte des fichiers glissés depuis l'explorateur."""

    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            self.files_dropped.emit(files)
            e.acceptProposedAction()


class TaskDialog(QDialog):
    def __init__(self, ctx, task_id: Optional[int] = None, defaults: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.task_id = task_id
        self.saved_id: Optional[int] = None
        self.pending: list[tuple[str, bool]] = []  # fichiers à joindre après création de la tâche
        self.setWindowTitle("Nouvelle tâche" if task_id is None else f"Tâche #{task_id}")
        self.resize(760, 640)
        self.task = ctx.tasks.get(task_id) if task_id else None

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_details()
        self._build_attachments()
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
        self.event_combo = QComboBox()
        self.event_combo.setToolTip("Rattache la tâche à un événement (culte, réunion…). La tâche reste une tâche.")
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
        form.addRow("Événement lié", self.event_combo)
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
        self._fill_events()
        self.event_combo.currentIndexChanged.connect(self._event_chosen)
        for s in self.ctx.statuses.list():
            self.status.addItem(s.label, s.id)
        for p in PRIORITIES:
            self.priority.addItem(PRIORITY_LABELS[p], p)
        self.priority.setCurrentIndex(PRIORITIES.index("normal"))

    def _fill_events(self) -> None:
        today = self.ctx.clock().date()
        self.event_combo.addItem("Aucun", None)
        shown = set()
        for e in self.ctx.events.list(frm=today - timedelta(days=14), to=today + timedelta(days=150)):
            when = f"{e.date:%d/%m/%Y}" + (f" {e.start_time:%H:%M}" if e.start_time else "")
            self.event_combo.addItem(f"🗓 {e.title} — {when}", e.id)
            shown.add(e.id)
        cur = self.task.event_id if self.task else None
        if cur and cur not in shown:  # événement lié hors de la plage affichée
            try:
                e = self.ctx.events.get(cur)
                self.event_combo.addItem(f"🗓 {e.title} — {e.date:%d/%m/%Y}", cur)
            except Exception:
                pass

    def _event_chosen(self) -> None:
        """Une tâche sans date rattachée à un événement prend la date de cet événement."""
        eid = self.event_combo.currentData()
        if eid and not self.deadline.value() and not self.start_date.value() and not getattr(self, "_loading_form", False):
            e = self.ctx.events.get(eid)
            self.start_date.set_value(e.date)
            self.deadline.set_value(e.date)

    @staticmethod
    def _h(*widgets) -> QWidget:
        w = QWidget(); lay = QHBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            lay.addWidget(x, 1 if not isinstance(x, QLabel) else 0)
        return w

    def _load(self, defaults: dict) -> None:
        t = self.task
        self._loading_form = True
        if t:
            self.event_combo.setCurrentIndex(max(0, self.event_combo.findData(t.event_id)))
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
        self._loading_form = False

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
            extra_date=self.task.extra_date if self.task else None, event_id=self.event_combo.currentData(),
            source="Saisie manuelle" if not self.task else self.task.source,
        )

    def _save(self) -> None:
        try:
            data = self._collect()
            if self.task:
                t = self.ctx.tasks.update(self.task.id, data)
            else:
                t = self.ctx.tasks.create(data)
                for path, copy in self.pending:
                    self.ctx.attachments.add(t.id, path, copy)
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


    # ------------------------------------------------------------ onglet Pièces jointes
    def _build_attachments(self) -> None:
        page = QWidget(); lay = QVBoxLayout(page)
        hint = QLabel("Photos, Word, Excel, PowerPoint, PDF… Les fichiers sont rangés dans le dossier des pièces jointes "
                      "(réglable dans Paramètres), pas dans la base de données. Glissez-déposez des fichiers ici.")
        hint.setWordWrap(True); hint.setObjectName("muted")
        lay.addWidget(hint)
        self.att_list = DropList()
        self.att_list.itemDoubleClicked.connect(lambda *_: self._att_open())
        self.att_list.files_dropped.connect(self._att_add_files)
        lay.addWidget(self.att_list, 1)
        self.att_copy = QCheckBox("Copier le fichier dans le dossier des pièces jointes (recommandé) — sinon seul un lien est conservé")
        self.att_copy.setChecked(True)
        lay.addWidget(self.att_copy)
        row = QHBoxLayout()
        for label, fn in (("＋ Ajouter des fichiers…", self._att_pick), ("Ouvrir", self._att_open),
                          ("Afficher dans l'explorateur", self._att_reveal), ("Retirer", self._att_remove)):
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.tabs.addTab(page, "Pièces jointes")
        self._att_refresh()

    def _att_refresh(self) -> None:
        self.att_list.clear()
        if self.task:
            for a in self.ctx.attachments.list(self.task.id):
                ok = self.ctx.attachments.exists(a)
                size = f"{(a.size or 0) / 1024:,.0f} Ko".replace(",", " ")
                item = QListWidgetItem(f"{ICONS.get(Path(a.display_name).suffix.lower(), '📎')}  {a.display_name}   ·   {size}"
                                       + ("" if ok else "   ⚠ fichier introuvable"))
                item.setData(Qt.UserRole, ("saved", a.id))
                if not ok:
                    item.setToolTip(f"Introuvable : {self.ctx.attachments.resolve(a)}")
                self.att_list.addItem(item)
        for path, copy in self.pending:
            item = QListWidgetItem(f"{ICONS.get(Path(path).suffix.lower(), '📎')}  {Path(path).name}   ·   (sera joint à l'enregistrement)")
            item.setData(Qt.UserRole, ("pending", path))
            self.att_list.addItem(item)
        self.tabs.setTabText(self.tabs.indexOf(self.att_list.parentWidget()), f"Pièces jointes ({self.att_list.count()})"
                             if self.att_list.count() else "Pièces jointes")

    def _att_pick(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Choisir les fichiers à joindre")
        if files:
            self._att_add_files(files)

    def _att_add_files(self, files: list) -> None:
        for path in files:
            try:
                if self.task:
                    self.ctx.attachments.add(self.task.id, path, self.att_copy.isChecked())
                elif Path(path).is_file():
                    self.pending.append((path, self.att_copy.isChecked()))
            except Exception as exc:
                show_error(self, exc, "Pièce jointe impossible")
        self._att_refresh()

    def _att_current(self):
        it = self.att_list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _att_path(self, cur) -> Optional[Path]:
        kind, val = cur
        return Path(val) if kind == "pending" else self.ctx.attachments.resolve(self.ctx.attachments.get(val))

    def _att_open(self) -> None:
        cur = self._att_current()
        if not cur:
            return
        p = self._att_path(cur)
        if not p.is_file():
            return QMessageBox.warning(self, "Fichier introuvable", f"Le fichier n'existe plus à cet emplacement :\n{p}")
        try:
            osutils.open_path(p)
        except OSError as exc:
            show_error(self, exc, "Ouverture impossible")

    def _att_reveal(self) -> None:
        cur = self._att_current()
        if cur:
            osutils.reveal_in_explorer(self._att_path(cur))

    def _att_remove(self) -> None:
        cur = self._att_current()
        if not cur:
            return
        kind, val = cur
        if kind == "pending":
            self.pending = [x for x in self.pending if x[0] != val]
        else:
            att = self.ctx.attachments.get(val)
            box = QMessageBox(QMessageBox.Question, "Retirer la pièce jointe", f"Retirer « {att.display_name} » de la tâche ?", parent=self)
            keep = box.addButton("Retirer (garder le fichier)", QMessageBox.AcceptRole)
            kill = box.addButton("Retirer et supprimer le fichier" if att.is_relative else "Retirer", QMessageBox.DestructiveRole)
            box.addButton("Annuler", QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked not in (keep, kill):
                return
            self.ctx.attachments.remove(val, delete_file=(clicked is kill and att.is_relative))
        self._att_refresh()
