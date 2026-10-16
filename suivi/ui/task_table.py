"""Tableau de tâches réutilisable (modèle + délégués + menu contextuel)."""
from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHeaderView, QMenu, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView,
)

from ..core import rules
from ..core.models import PRIORITIES, PRIORITY_LABELS, Task
from . import theme
from .common import confirm, due_text, fmt_date, show_error

COLUMNS = [
    ("Priorité", "priority", 90),
    ("Intitulé", "title", 380),
    ("Projet", "project", 120),
    ("Statut", "status", 110),
    ("Responsable", "assignee", 110),
    ("Début", "start", 90),
    ("Deadline", "deadline", 90),
    ("Échéance", None, 120),
    ("Modifiée le", "updated", 100),
]


class TaskModel(QAbstractTableModel):
    def __init__(self, today_fn):
        super().__init__()
        self.tasks: list[Task] = []
        self._today = today_fn

    def set_tasks(self, tasks: list[Task]) -> None:
        self.beginResetModel()
        self.tasks = tasks
        self.endResetModel()

    def task_at(self, row: int) -> Optional[Task]:
        return self.tasks[row] if 0 <= row < len(self.tasks) else None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.tasks)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section][0]
        return None

    def data(self, index, role=Qt.DisplayRole):
        t = self.tasks[index.row()]
        c = index.column()
        today = self._today()
        if role == Qt.UserRole:
            return t
        if role == Qt.DisplayRole:
            return [
                t.priority_label, ("↻ " if t.series_id else "") + ("🗓 " if t.event_id else "") + ("📎 " if t.n_attach else "") + t.title, t.project_name, t.status_label, t.assignee,
                fmt_date(t.start_date), fmt_date(t.deadline), due_text(t, today), t.updated_at.strftime("%d/%m/%Y"),
            ][c]
        if role == Qt.ToolTipRole and c == 1:
            return t.title + (f"\n🗓 Événement : {t.event_title}" if t.event_id else "") + (f"\n\n{t.description}" if t.description else "")
        if role == Qt.ForegroundRole:
            if t.is_closed:
                return QBrush(QColor(theme.MUTED))
            if c == 7 and rules.is_overdue(t, today):
                return QBrush(QColor(theme.DANGER))
            if c == 7 and t.deadline == today:
                return QBrush(QColor(theme.WARNING))
        if role == Qt.FontRole:
            f = QFont()
            if c == 7 and not t.is_closed and t.deadline and t.deadline <= today:
                f.setBold(True)
            if t.is_closed and c == 1:
                f.setStrikeOut(t.status_kind == "cancelled")
            return f
        if role == Qt.BackgroundRole and rules.is_overdue(t, today):
            return QBrush(QColor("#FEF2F2"))
        return None


class ChipDelegate(QStyledItemDelegate):
    """Dessine priorité (pastille) et statut (étiquette colorée)."""

    def paint(self, painter: QPainter, option, index):
        t: Task = index.data(Qt.UserRole)
        col = index.column()
        if col not in (0, 3):
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)  # fond / sélection sans le texte (dessiné ci-dessous)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 5, -6, -5)
        if col == 3:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.status_color))
            painter.drawRoundedRect(r, 9, 9)
            painter.setPen(theme.contrast_text(t.status_color))
            f = painter.font(); f.setPointSizeF(8.5); f.setBold(True); painter.setFont(f)
            painter.drawText(r, Qt.AlignCenter, t.status_label)
        else:
            color = QColor(theme.PRIORITY_COLORS[t.priority])
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(r.left() + 2, r.center().y() - 5, 10, 10))
            painter.setPen(QColor(theme.TEXT) if not t.is_closed else QColor(theme.MUTED))
            painter.drawText(r.adjusted(18, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, t.priority_label)
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 30))
        return s


class TaskTable(QTableView):
    edit_requested = Signal(int)
    sort_changed = Signal(str, bool)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.model_ = TaskModel(lambda: ctx.clock().date())
        self.setModel(self.model_)
        self.setItemDelegate(ChipDelegate(self))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(32)
        hdr = self.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setStretchLastSection(False)
        for i, (_, _, w) in enumerate(COLUMNS):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)
            self.setColumnWidth(i, w)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionsClickable(True)
        hdr.sectionClicked.connect(self._header_clicked)
        self._sort_key, self._desc = "deadline", False
        self.setWordWrap(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.doubleClicked.connect(lambda idx: self.edit_requested.emit(self.model_.tasks[idx.row()].id))

    # tri : pris en charge côté requête (les tâches sans deadline restent en fin de liste)
    def _header_clicked(self, section: int) -> None:
        key = COLUMNS[section][1]
        if not key:
            return
        self._desc = (not self._desc) if key == self._sort_key else False
        self._sort_key = key
        self.show_sort_indicator()
        self.sort_changed.emit(key, self._desc)

    def show_sort_indicator(self) -> None:
        for i, (_, k, _) in enumerate(COLUMNS):
            if k == self._sort_key:
                self.horizontalHeader().setSortIndicator(i, Qt.DescendingOrder if self._desc else Qt.AscendingOrder)
                self.horizontalHeader().setSortIndicatorShown(True)
                return

    def set_sort(self, key: str, desc: bool) -> None:
        self._sort_key, self._desc = key, desc
        self.show_sort_indicator()

    def selected_tasks(self) -> list[Task]:
        rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        return [self.model_.tasks[r] for r in rows]

    def set_tasks(self, tasks: list[Task]) -> None:
        keep = {t.id for t in self.selected_tasks()}
        self.model_.set_tasks(tasks)
        sm = self.selectionModel()
        for r, t in enumerate(tasks):
            if t.id in keep:
                sm.select(self.model_.index(r, 0), sm.SelectionFlag.Select | sm.SelectionFlag.Rows)

    # -- menu contextuel ------------------------------------------------------------
    def _menu(self, pos) -> None:
        sel = self.selected_tasks()
        if not sel:
            return
        svc = self.ctx.tasks
        menu = QMenu(self)
        one = sel[0]
        act = menu.addAction("Ouvrir / modifier…")
        act.triggered.connect(lambda: self.edit_requested.emit(one.id))
        if len(sel) == 1 or True:
            done = menu.addAction("✔  Marquer comme terminée")
            done.triggered.connect(lambda: self._run(lambda t: svc.complete(t.id), sel))
        st_menu = menu.addMenu("Changer le statut")
        for st in self.ctx.statuses.list():
            a = st_menu.addAction(st.label)
            a.triggered.connect(lambda _=False, sid=st.id: self._run(lambda t: svc.set_status(t.id, sid), sel))
        pr_menu = menu.addMenu("Changer la priorité")
        for p in PRIORITIES:
            a = pr_menu.addAction(PRIORITY_LABELS[p])
            a.triggered.connect(lambda _=False, pr=p: self._run(
                lambda t: svc.update(t.id, svc.to_input(t, priority=pr)), sel))
        spaces = [s for s in self.ctx.spaces.list(enabled_only=True) if s.id != one.space_id]
        if spaces:
            mv = menu.addMenu("Déplacer vers l'espace")
            for s in spaces:
                a = mv.addAction(f"{s.icon}  {s.name}")
                a.triggered.connect(lambda _=False, sid=s.id: self._run(lambda t: svc.move_to_space(t.id, sid), sel))
        menu.addSeparator()
        dele = menu.addAction("Supprimer (corbeille)…")
        dele.triggered.connect(lambda: self.delete_selected())
        menu.exec(self.viewport().mapToGlobal(pos))

    def _run(self, fn, tasks) -> None:
        try:
            with self.ctx.tasks.batch():
                for t in tasks:
                    fn(t)
        except Exception as exc:
            show_error(self, exc)

    def delete_selected(self) -> None:
        sel = self.selected_tasks()
        if not sel:
            return
        msg = (f"Mettre {len(sel)} tâche(s) à la corbeille ?\n\nElles pourront être restaurées depuis "
               "Historique > Corbeille.")
        if confirm(self, "Supprimer", msg, "Mettre à la corbeille", danger=True):
            self._run(lambda t: self.ctx.tasks.delete(t.id), sel)
