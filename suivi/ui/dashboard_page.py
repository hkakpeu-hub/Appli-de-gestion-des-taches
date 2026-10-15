"""Tableau de bord : indicateurs, listes à traiter, graphiques. Se met à jour à chaque changement de données."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QAbstractItemView,
)

from ..core import metrics
from ..core.models import Task
from . import theme
from .charts import ColumnChart, DonutChart, HBarChart, LineChart
from .common import Card, Page, due_text, fmt_date
from .task_dialog import TaskDialog


class Kpi(QFrame):
    clicked = Signal()

    def __init__(self, label: str, color: str = theme.TEXT):
        super().__init__()
        self.setObjectName("kpi")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)
        self.value = QLabel("0"); self.value.setObjectName("kpiValue")
        self.value.setStyleSheet(f"color: {color};")
        self.label = QLabel(label); self.label.setObjectName("kpiLabel")
        lay.addWidget(self.value); lay.addWidget(self.label)

    def set_value(self, v) -> None:
        self.value.setText(str(v))

    def mousePressEvent(self, e):
        self.clicked.emit()


class DashboardPage(Page):
    navigate = Signal(str, object)  # (vue prédéfinie, id_projet|None)

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget(); body.setObjectName("content")
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)

        head = QHBoxLayout()
        box = QVBoxLayout(); box.setSpacing(0)
        t = QLabel("Tableau de bord"); t.setObjectName("pageTitle")
        self.sub = QLabel(); self.sub.setObjectName("muted")
        box.addWidget(t); box.addWidget(self.sub)
        head.addLayout(box); head.addStretch()
        root.addLayout(head)

        # --- indicateurs
        grid = QGridLayout(); grid.setSpacing(12)
        specs = [
            ("total", "Tâches au total", theme.TEXT, "all"),
            ("done", "Terminées", theme.SUCCESS, "done"),
            ("in_progress", "En cours", theme.ACCENT, "in_progress"),
            ("todo", "À faire", "#64748B", "todo"),
            ("overdue", "En retard", theme.DANGER, "overdue"),
            ("due_today", "Échéance aujourd'hui", theme.WARNING, "due_today"),
            ("due_soon", "Échéances à venir", "#0891B2", "upcoming"),
            ("blocked", "Bloquées", "#B91C1C", "blocked"),
        ]
        self.kpis: dict[str, Kpi] = {}
        for i, (key, label, color, view) in enumerate(specs):
            k = Kpi(label, color)
            k.clicked.connect(lambda v=view: self.navigate.emit(v, None))
            self.kpis[key] = k
            grid.addWidget(k, i // 4, i % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        root.addLayout(grid)

        prog = Card()
        row = QHBoxLayout()
        row.addWidget(QLabel("Taux d'avancement global"))
        self.prog_label = QLabel(); self.prog_label.setStyleSheet("font-weight:700;")
        row.addStretch(); row.addWidget(self.prog_label)
        prog.lay.addLayout(row)
        self.bar = QProgressBar(); self.bar.setTextVisible(False); self.bar.setFixedHeight(12)
        self.bar.setStyleSheet(f"QProgressBar{{background:#E6EAF1;border-radius:6px;border:none;}}"
                               f"QProgressBar::chunk{{background:{theme.SUCCESS};border-radius:6px;}}")
        prog.lay.addWidget(self.bar)
        root.addWidget(prog)

        # --- listes à traiter
        lists = Card("À traiter")
        self.tabs = QTabWidget()
        self.lists: dict[str, QListWidget] = {}
        self.tab_defs = [
            ("overdue", "En retard"), ("today", "Aujourd'hui"), ("upcoming", "Prochaines échéances"),
            ("blocked", "Bloquées"), ("late_start", "Début dépassé"), ("no_deadline", "Sans échéance"),
            ("stale", "Sans mise à jour"),
        ]
        for key, label in self.tab_defs:
            lw = QListWidget(); lw.setMinimumHeight(190)
            lw.itemDoubleClicked.connect(lambda it: TaskDialog(self.ctx, it.data(Qt.UserRole), None, self).exec())
            self.lists[key] = lw
            self.tabs.addTab(lw, label)
        lists.lay.addWidget(self.tabs)
        root.addWidget(lists)

        # --- graphiques
        charts = QGridLayout(); charts.setSpacing(12)
        self.c_projects = DonutChart(); self.c_top = HBarChart(); self.c_status = HBarChart()
        self.c_done = LineChart(); self.c_late = HBarChart(); self.c_load = ColumnChart()
        for ch in (self.c_projects, self.c_top, self.c_late):
            ch.clicked.connect(self._project_clicked)
        self.c_status.clicked.connect(lambda lab: None)
        for i, (title, widget) in enumerate([
            ("Répartition des tâches par projet", self.c_projects),
            ("Projets qui concentrent le plus d'actions", self.c_top),
            ("Tâches par statut", self.c_status),
            ("Retards par projet", self.c_late),
            ("Charge par semaine (tâches ouvertes selon deadline)", self.c_load),
        ]):
            card = Card(title); card.lay.addWidget(widget)
            charts.addWidget(card, i // 2, i % 2)
        done_card = Card("Tâches terminées dans le temps")
        self.gran = QPushButton("Vue : par mois"); self.gran.setCheckable(True)
        self.gran.toggled.connect(lambda on: (self.gran.setText("Vue : par semaine" if on else "Vue : par mois"), self.refresh()))
        done_card.lay.addWidget(self.gran, 0, Qt.AlignRight)
        done_card.lay.addWidget(self.c_done)
        charts.addWidget(done_card, 2, 1)
        charts.setColumnStretch(0, 1); charts.setColumnStretch(1, 1)
        root.addLayout(charts)

        # --- classement des projets
        rank = Card("Classement des projets (indice de charge = retards ×3 + bloquées ×2 + actions ouvertes)")
        self.rank = QTableWidget(0, 7)
        self.rank.setHorizontalHeaderLabels(["Projet", "Actions", "Ouvertes", "En retard", "Bloquées", "Terminées", "Indice"])
        self.rank.verticalHeader().setVisible(False)
        self.rank.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rank.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rank.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.rank.setMinimumHeight(260)
        self.rank.cellDoubleClicked.connect(self._rank_clicked)
        rank.lay.addWidget(self.rank)
        root.addWidget(rank)

    # ---------------------------------------------------------------------------
    def _project_clicked(self, name: str) -> None:
        p = self.ctx.projects.by_name(name)
        if p:
            self.navigate.emit("all", p.id)

    def _rank_clicked(self, row: int, _col: int) -> None:
        self._project_clicked(self.rank.item(row, 0).text())

    def refresh(self) -> None:
        now = self.ctx.clock()
        settings = self.ctx.settings.all()
        tasks = self.ctx.tasks.all()
        d = metrics.compute_dashboard(tasks, now, settings)
        self.sub.setText(f"Situation au {now:%d/%m/%Y à %H:%M} · mise à jour automatique")
        for key in self.kpis:
            self.kpis[key].set_value(getattr(d, key))
        self.bar.setValue(int(d.progress * 100))
        self.prog_label.setText(f"{d.progress:.0%}   ({d.done} terminées sur {d.total - d.cancelled} tâches hors annulées)")

        today = now.date()
        data = {
            "overdue": d.overdue_tasks, "today": d.today_tasks, "upcoming": d.upcoming_tasks, "blocked": d.blocked_tasks,
            "late_start": d.late_start_tasks, "no_deadline": d.no_deadline_tasks, "stale": d.stale_tasks,
        }
        for i, (key, label) in enumerate(self.tab_defs):
            lw = self.lists[key]
            lw.clear()
            for t in data[key][:60]:
                extra = {"overdue": due_text(t, today), "upcoming": due_text(t, today) + " · " + fmt_date(t.deadline),
                         "late_start": f"début prévu {fmt_date(t.start_date)}", "stale": f"maj {t.updated_at:%d/%m/%Y}",
                         "blocked": t.status_label, "today": t.status_label, "no_deadline": t.status_label}[key]
                it = QListWidgetItem(f"{t.title}   —   {t.project_name or 'sans projet'}  ·  {extra}")
                it.setData(Qt.UserRole, t.id)
                lw.addItem(it)
            if len(data[key]) > 60:
                lw.addItem(QListWidgetItem(f"… et {len(data[key]) - 60} autre(s) — ouvrez « Toutes les tâches »"))
            self.tabs.setTabText(i, f"{label} ({len(data[key])})")

        projs = d.projects
        self.c_projects.set_data([(p.name, p.total, p.color) for p in sorted(projs, key=lambda p: -p.total)], f"{d.total}")
        self.c_top.set_data([(p.name, p.total, p.color, f"{p.name} : {p.total} actions ({p.active} ouvertes, {p.done} terminées)")
                             for p in sorted(projs, key=lambda p: -p.total)[:8]])
        self.c_status.set_data([(lab, n, col) for lab, col, n in d.by_status])
        self.c_late.set_data([(p.name, p.overdue, theme.DANGER) for p in sorted(projs, key=lambda p: -p.overdue) if p.overdue][:8])
        self.c_done.set_data(metrics.completed_series(tasks, today, "week" if self.gran.isChecked() else "month", 0))
        self.c_load.set_data([(w, n, theme.ACCENT, f"Semaine du {w} : {n} tâche(s), {m // 60} h {m % 60:02d} estimées")
                              for w, n, m in d.workload_series])
        self.rank.setRowCount(len(projs))
        for r, p in enumerate(projs):
            vals = [p.name, p.total, p.active, p.overdue, p.blocked, f"{p.done} ({p.done_ratio:.0%})", f"{p.score:g}"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c:
                    it.setTextAlignment(Qt.AlignCenter)
                if c == 3 and p.overdue:
                    it.setForeground(Qt.red)
                self.rank.setItem(r, c, it)
