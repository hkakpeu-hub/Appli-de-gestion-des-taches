"""Pages « Toutes les tâches » et « Mes tâches du jour » : recherche, filtres combinables, tri, actions."""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..core import rules
from ..core.models import PRIORITIES, PRIORITY_LABELS
from ..core.presets import MENU_PRESETS, PRESET_LABELS, make_filter
from ..core.tasks import TaskFilter
from ..excel.exporter import export_tasks
from .common import Card, OptDate, Page, confirm, debounce, page_header, show_error
from .task_dialog import TaskDialog
from .task_table import TaskTable


class TasksPage(Page):
    def __init__(self, ctx, mode: str = "all", parent=None):
        super().__init__(ctx, parent)
        self.mode = mode  # "all" | "today"
        self._base_key = "today" if mode == "today" else "all"
        self._base_project: Optional[int] = None
        self._loading = False
        self.last_filter = TaskFilter()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(10)
        title = "Mes tâches du jour" if mode == "today" else "Toutes les tâches"
        sub = ("Échéances et débuts d'aujourd'hui, et tâches en cours." if mode == "today"
               else "Recherchez, filtrez et gérez l'ensemble de vos tâches.")
        header, hrow, self.sub = page_header(title, sub)
        add = QPushButton("＋ Nouvelle tâche"); add.setObjectName("primary")
        add.clicked.connect(lambda: self.new_task())
        hrow.addWidget(add)
        root.addWidget(header)

        # --- barre de recherche + vue
        bar = QHBoxLayout()
        self.search = QLineEdit(); self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("🔍  Rechercher (intitulé, description, projet, commentaire, responsable)…")
        bar.addWidget(self.search, 1)
        self.view = QComboBox()
        for k in MENU_PRESETS:
            self.view.addItem(PRESET_LABELS[k], k)
        self.view.setMinimumWidth(230)
        self.view.setVisible(mode == "all")
        bar.addWidget(self.view)
        reset = QPushButton("Réinitialiser")
        reset.clicked.connect(self.reset_filters)
        bar.addWidget(reset)
        root.addLayout(bar)

        # --- filtres
        fl = QHBoxLayout()
        self.f_project = QComboBox(); self.f_status = QComboBox(); self.f_assignee = QComboBox()
        self.f_priority = QComboBox(); self.f_delay = QComboBox(); self.f_field = QComboBox()
        for lab, w in (("Projet", self.f_project), ("Statut", self.f_status), ("Responsable", self.f_assignee),
                       ("Priorité", self.f_priority), ("Retard", self.f_delay)):
            box = QVBoxLayout(); box.setSpacing(2)
            l = QLabel(lab); l.setObjectName("muted")
            box.addWidget(l); box.addWidget(w)
            fl.addLayout(box)
        self.f_field.addItem("Deadline", "deadline"); self.f_field.addItem("Date de début", "start_date")
        self.f_field.addItem("Date de création", "created_at")
        self.f_from = OptDate("du"); self.f_to = OptDate("au")
        pbox = QVBoxLayout(); pbox.setSpacing(2)
        l = QLabel("Période"); l.setObjectName("muted"); pbox.addWidget(l)
        prow = QHBoxLayout(); prow.addWidget(self.f_field); prow.addWidget(self.f_from); prow.addWidget(self.f_to)
        pbox.addLayout(prow)
        fl.addLayout(pbox, 2)
        self.f_active = QCheckBox("Masquer terminées / annulées")
        fl.addWidget(self.f_active)
        root.addLayout(fl)

        # --- tableau
        self.table = TaskTable(ctx)
        root.addWidget(self.table, 1)
        self.table.edit_requested.connect(self.edit_task)
        self.table.sort_changed.connect(lambda k, d: self.reload())

        # --- pied
        foot = QHBoxLayout()
        self.count = QLabel(); self.count.setObjectName("muted")
        foot.addWidget(self.count)
        foot.addStretch()
        b_done = QPushButton("✔ Terminer la sélection"); b_done.clicked.connect(self._complete_sel)
        b_edit = QPushButton("Modifier…"); b_edit.clicked.connect(self._edit_sel)
        b_del = QPushButton("Supprimer…"); b_del.setObjectName("danger"); b_del.clicked.connect(self.table.delete_selected)
        b_exp = QPushButton("Exporter la vue (Excel)…"); b_exp.clicked.connect(self.export_view)
        for b in (b_done, b_edit, b_del, b_exp):
            foot.addWidget(b)
        root.addLayout(foot)

        self._debounce = debounce(250, self.reload)
        self.search.textChanged.connect(lambda *_: self._debounce.start())
        for w in (self.f_project, self.f_status, self.f_assignee, self.f_priority, self.f_delay, self.f_field):
            w.currentIndexChanged.connect(self._filters_changed)
        for w in (self.f_from, self.f_to):
            w.changed.connect(self._filters_changed)
        self.f_active.toggled.connect(self._filters_changed)
        self.view.currentIndexChanged.connect(self._view_changed)
        self._fill_combos()

    # ------------------------------------------------------------------ combos
    def _fill_combos(self) -> None:
        self._loading = True
        def refill(box: QComboBox, first: str, items):
            cur = box.currentData()
            box.clear(); box.addItem(first, None)
            for label, data in items:
                box.addItem(label, data)
            i = box.findData(cur)
            box.setCurrentIndex(max(0, i))
        refill(self.f_project, "Tous", [(p.name, p.id) for p in self.ctx.projects.list()])
        refill(self.f_status, "Tous", [(s.label, s.id) for s in self.ctx.statuses.list()])
        refill(self.f_assignee, "Tous", [(a, a) for a in self.ctx.tasks.assignees()])
        refill(self.f_priority, "Toutes", [(PRIORITY_LABELS[p], p) for p in PRIORITIES])
        refill(self.f_delay, "Indifférent", [(v, k) for k, v in rules.DELAY_LEVELS.items()])
        self._loading = False

    # ------------------------------------------------------------------ filtre
    def current_filter(self) -> TaskFilter:
        now = self.ctx.clock()
        f = make_filter(self._base_key, now, self.ctx.settings.all(), self._base_project)
        f.text = self.search.text()
        if self.f_project.currentData():
            f.project_ids = [self.f_project.currentData()]
        if self.f_status.currentData():
            f.status_ids = [self.f_status.currentData()]
        if self.f_assignee.currentData():
            f.assignee = self.f_assignee.currentData()
        if self.f_priority.currentData():
            f.priorities = [self.f_priority.currentData()]
        if self.f_delay.currentData():
            f.delay = self.f_delay.currentData()
        if self.f_from.value() or self.f_to.value():
            f.date_field = self.f_field.currentData()
            f.date_from, f.date_to = self.f_from.value(), self.f_to.value()
            f.involving = None
        f.only_active = f.only_active or self.f_active.isChecked()
        f.sort, f.descending = self.table._sort_key, self.table._desc
        return f

    def reload(self) -> None:
        if self._loading:
            return
        try:
            flt = self.current_filter()
            tasks = self.ctx.tasks.list(flt, self.ctx.clock().date())
        except Exception as exc:
            return show_error(self, exc)
        self.last_filter = flt
        self.table.set_tasks(tasks)
        total = len(self.ctx.tasks.all())
        self.count.setText(f"{len(tasks)} tâche(s) affichée(s) sur {total}")

    def refresh(self) -> None:
        self._fill_combos()
        self.reload()

    def _filters_changed(self, *_) -> None:
        if not self._loading:
            self.reload()

    def _view_changed(self) -> None:
        if self._loading:
            return
        self.set_view(self.view.currentData(), None, reset_manual=False)

    def set_view(self, key: str, project_id: Optional[int] = None, reset_manual: bool = True) -> None:
        """Applique une vue prédéfinie (depuis le menu, le tableau de bord ou la page Projets)."""
        self._base_key, self._base_project = key, project_id
        if self.mode == "all":
            self._loading = True
            self.view.setCurrentIndex(max(0, self.view.findData(key)))
            self._loading = False
        base = make_filter(key, self.ctx.clock(), self.ctx.settings.all())
        self.table.set_sort(base.sort, base.descending)
        if reset_manual:
            self.reset_filters(keep_view=True)
        else:
            self.reload()
        if project_id:
            name = self.ctx.projects.get(project_id).name
            self.sub.setText(f"Vue : {PRESET_LABELS.get(key, key)} — projet « {name} »")
        else:
            self.sub.setText(f"Vue : {PRESET_LABELS.get(key, key)}")

    def reset_filters(self, keep_view: bool = False) -> None:
        self._loading = True
        self.search.clear()
        for w in (self.f_project, self.f_status, self.f_assignee, self.f_priority, self.f_delay):
            w.setCurrentIndex(0)
        self.f_from.set_value(None); self.f_to.set_value(None); self.f_active.setChecked(False)
        if not keep_view:
            self._base_key = "today" if self.mode == "today" else "all"
            self._base_project = None
            if self.mode == "all":
                self.view.setCurrentIndex(self.view.findData("all"))
            base = make_filter(self._base_key, self.ctx.clock(), self.ctx.settings.all())
            self.table.set_sort(base.sort, base.descending)
            self.sub.setText("Échéances et débuts d'aujourd'hui, et tâches en cours." if self.mode == "today"
                             else "Recherchez, filtrez et gérez l'ensemble de vos tâches.")
        self._loading = False
        self.reload()

    # ------------------------------------------------------------------ actions
    def new_task(self, defaults: Optional[dict] = None) -> None:
        dlg = TaskDialog(self.ctx, None, defaults, self)
        dlg.exec()

    def edit_task(self, task_id: int) -> None:
        TaskDialog(self.ctx, task_id, None, self).exec()

    def _edit_sel(self) -> None:
        sel = self.table.selected_tasks()
        if sel:
            self.edit_task(sel[0].id)

    def _complete_sel(self) -> None:
        sel = self.table.selected_tasks()
        try:
            with self.ctx.tasks.batch():
                for t in sel:
                    self.ctx.tasks.complete(t.id)
        except Exception as exc:
            show_error(self, exc)

    def export_view(self) -> None:
        tasks = self.table.model_.tasks
        if not tasks:
            QMessageBox.information(self, "Export", "Aucune tâche à exporter dans la vue actuelle.")
            return
        stamp = self.ctx.clock().strftime("%Y%m%d_%H%M")
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la vue", f"taches_{stamp}.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        try:
            n = export_tasks(self.ctx.tasks, tasks, path)
            QMessageBox.information(self, "Export terminé", f"{n} tâche(s) exportée(s) vers :\n{path}")
        except Exception as exc:
            show_error(self, exc, "Export impossible (le fichier est-il ouvert dans Excel ?)")
