"""Fenêtre principale : navigation latérale, saisie rapide, alertes périodiques, zone de notification."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..core.alerts import LEVELS
from ..core.quickadd import parse_quick
from ..core.spaces import CURRENT
from . import theme
from .ai_page import AIPage
from .alerts_page import AlertsPage
from .common import show_error
from .dashboard_page import DashboardPage
from .history_page import HistoryPage
from .home_page import HomePage
from .io_page import IOPage
from .planning_page import PlanningPage
from .projects_page import ProjectsPage
from .settings_page import SettingsPage
from .task_dialog import TaskDialog
from .tasks_page import TasksPage

log = logging.getLogger(__name__)


def make_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(theme.ACCENT)); p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(size * .04, size * .04, size * .92, size * .92), size * .2, size * .2)
        p.setPen(QColor("white")); p.setBrush(Qt.NoBrush)
        pen = p.pen(); pen.setWidthF(size * .1); pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin); p.setPen(pen)
        p.drawPolyline([QPointF(size * .27, size * .52), QPointF(size * .43, size * .68), QPointF(size * .74, size * .33)])
        p.end()
        icon.addPixmap(pm)
    return icon


NAV = [
    ("dashboard", "▦  Tableau de bord"), ("tasks", "☰  Toutes les tâches"), ("today", "★  Mes tâches du jour"),
    ("projects", "▣  Projets"), ("planning", "▤  Calendrier et planning"), ("alerts", "🔔  Alertes"),
    ("io", "⇅  Importation / exportation"), ("history", "↺  Historique"), ("settings", "⚙  Paramètres"),
    ("ai", "✦  Assistant IA"),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._quitting = False
        self._closed = False
        self._last_day = ctx.clock().date()
        self._tray_hint_shown = False
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(make_icon())
        self.resize(1360, 860)
        self.setMinimumSize(1000, 640)

        self.root_stack = QStackedWidget(); self.setCentralWidget(self.root_stack)
        self.home = HomePage(ctx)
        central = QWidget()  # espace de travail (barre latérale + pages)
        self.root_stack.addWidget(self.home); self.root_stack.addWidget(central)
        root = QHBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # --- barre latérale
        side = QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(232)
        sl = QVBoxLayout(side); sl.setContentsMargins(0, 0, 0, 10); sl.setSpacing(0)
        home_btn = QPushButton("‹  Accueil"); home_btn.setObjectName("nav"); home_btn.setCursor(Qt.PointingHandCursor)
        home_btn.clicked.connect(self.go_home)
        sl.addSpacing(8); sl.addWidget(home_btn)
        self.brand = QLabel(APP_NAME); self.brand.setObjectName("brand")
        self.brand_sub = QLabel("Tâches · projets · échéances"); self.brand_sub.setObjectName("brandSub")
        sl.addWidget(self.brand); sl.addWidget(self.brand_sub)
        self.nav_group = QButtonGroup(self); self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for i, (key, label) in enumerate(NAV):
            b = QPushButton(label); b.setObjectName("nav"); b.setCheckable(True); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            self.nav_group.addButton(b); sl.addWidget(b)
            self.nav_buttons[key] = b
        sl.addStretch()
        self.db_label = QLabel(f"v{__version__} · données locales"); self.db_label.setObjectName("brandSub")
        sl.addWidget(self.db_label)
        root.addWidget(side)

        # --- contenu
        content = QWidget(); content.setObjectName("content")
        cl = QVBoxLayout(content); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(0)
        top = QFrame(); top.setObjectName("topbar"); top.setStyleSheet(f"QFrame#topbar{{background:white;border-bottom:1px solid {theme.BORDER};}}")
        tl = QHBoxLayout(top); tl.setContentsMargins(24, 10, 24, 10)
        self.quick = QLineEdit()
        self.quick.setPlaceholderText("＋  Ajout rapide :  Relancer Donald  #Centaures  !demain  @Hermann   (Entrée pour créer)")
        self.quick.returnPressed.connect(self.quick_add)
        tl.addWidget(self.quick, 1)
        new = QPushButton("Nouvelle tâche (Ctrl+N)"); new.setObjectName("primary"); new.clicked.connect(self.new_task)
        tl.addWidget(new)
        cl.addWidget(top)
        self.stack = QStackedWidget(); cl.addWidget(self.stack, 1)
        root.addWidget(content, 1)

        # --- pages
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(ctx), "tasks": TasksPage(ctx, "all"), "today": TasksPage(ctx, "today"),
            "projects": ProjectsPage(ctx), "planning": PlanningPage(ctx), "alerts": AlertsPage(ctx),
            "history": HistoryPage(ctx), "settings": SettingsPage(ctx), "ai": AIPage(ctx),
        }
        self.pages["io"] = IOPage(ctx, lambda: self.pages["tasks"].last_filter)
        for key, _ in NAV:
            self.stack.addWidget(self.pages[key])
        self.pages["dashboard"].navigate.connect(self.open_view)
        self.pages["projects"].open_project.connect(lambda pid: self.open_view("all", pid))
        self.pages["settings"].settings_saved.connect(self._settings_changed)
        self.home.open_space.connect(self.enter_space)
        self.home.open_settings.connect(lambda: self._enter_for_settings())
        self.home.open_alerts.connect(self.open_alerts_center)
        self.home.open_module.connect(self.open_module)
        ctx.spaces.subscribe(self._data_changed)
        ctx.scope.subscribe(self._space_changed)

        # --- données -> interface
        ctx.tasks.subscribe(self._data_changed)
        ctx.projects.subscribe(self._data_changed)
        self._coalesce = QTimer(self); self._coalesce.setSingleShot(True); self._coalesce.setInterval(30)
        self._coalesce.timeout.connect(self._apply_data_change)
        ctx.alerts.subscribe(self._alerts_changed)

        # --- zone de notification
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction("Ouvrir").triggered.connect(self.show_window)
        menu.addAction("Alertes").triggered.connect(self.open_alerts_center)
        menu.addAction("Accueil").triggered.connect(lambda: (self.show_window(), self.go_home()))
        menu.addSeparator()
        menu.addAction("Quitter").triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu); self._tray_menu = menu
        self.tray.activated.connect(lambda r: self.show_window() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.messageClicked.connect(self.open_alerts_center)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        # --- raccourcis
        QShortcut(QKeySequence("Ctrl+N"), self, self.new_task)
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)
        QShortcut(QKeySequence("F5"), self, self.refresh_all)
        for i, (key, _) in enumerate(NAV[:9], start=1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, lambda k=key: self.go(k))

        # --- minuteries
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick)
        self.timer.start(int(ctx.settings.get("check_interval_seconds")) * 1000)

        self._space_changed()
        self.go_home()
        QTimer.singleShot(400, self.tick)

    # ------------------------------------------------------------------ navigation
    def go(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        self.nav_buttons[key].setChecked(True)
        self.pages[key].request_refresh()

    def go_home(self) -> None:
        self.root_stack.setCurrentWidget(self.home)
        self.home.request_refresh()
        self._update_badge()

    def enter_space(self, space_id: int) -> None:
        """Ouvre l'espace de travail (Travail, Personnel, Kingdom…) sur son tableau de bord."""
        if self.ctx.scope.space_id != space_id:
            self.ctx.scope.set(space_id)
        self.root_stack.setCurrentIndex(1)
        self.go("dashboard")
        self._update_badge()

    def _enter_for_settings(self) -> None:
        if self.ctx.scope.space_id is None:
            first = self.ctx.spaces.list(enabled_only=True)
            self.ctx.scope.set(first[0].id if first else 1)
        self.root_stack.setCurrentIndex(1)
        self.go("settings")

    def open_alerts_center(self) -> None:
        self.show_window()
        unread = self.ctx.alerts.visible(include_read=False)
        target = unread[0].space_id if unread else (self.ctx.scope.space_id or 1)
        if self.ctx.scope.space_id != target:
            self.ctx.scope.set(target)
        self.root_stack.setCurrentIndex(1)
        self.go("alerts")

    def open_module(self, key: str) -> None:
        QMessageBox.information(self, "Module", "Ce module n'est pas encore disponible.")

    def _space_changed(self) -> None:
        sid = self.ctx.scope.space_id
        try:
            sp = self.ctx.spaces.get(sid) if sid else None
        except Exception:
            sp = None
        self.brand.setText(f"{sp.icon} {sp.name}" if sp else APP_NAME)
        self.brand_sub.setText("Tâches · projets · échéances")
        self.quick.setPlaceholderText(
            f"＋  Ajout rapide dans « {sp.name if sp else '…'} » :  Relancer Donald  #Projet  !demain  @Responsable   (Entrée)")
        for key in ("tasks", "today"):
            self.pages[key].reset_filters()

    def open_view(self, view: str, project_id: Optional[int] = None) -> None:
        page = self.pages["today"] if view == "today" else self.pages["tasks"]
        self.go("today" if view == "today" else "tasks")
        if view != "today":
            page.set_view(view, project_id)

    def _focus_search(self) -> None:
        w = self.stack.currentWidget()
        if isinstance(w, TasksPage):
            w.search.setFocus()
            w.search.selectAll()
        else:
            self.open_view("all")
            self.pages["tasks"].search.setFocus()

    def new_task(self) -> None:
        if self.root_stack.currentWidget() is self.home:
            return
        TaskDialog(self.ctx, None, None, self).exec()

    def quick_add(self) -> None:
        text = self.quick.text().strip()
        if not text:
            return self.new_task()
        try:
            data = parse_quick(text, self.ctx.clock().date(), self.ctx.settings.get("assignee_default"))
            t = self.ctx.tasks.create(data)
        except Exception as exc:
            return show_error(self, exc, "Ajout rapide impossible")
        self.quick.clear()
        self.statusBar().showMessage(f"Tâche #{t.id} créée : {t.title}", 5000)

    # ------------------------------------------------------------------ rafraîchissement
    def _data_changed(self) -> None:
        self._coalesce.start()

    def _apply_data_change(self) -> None:
        if self._closed:
            return
        self.run_alerts(notify=True)
        for page in (*self.pages.values(), self.home):
            page.request_refresh()
        self._update_badge()

    def _alerts_changed(self) -> None:
        self._update_badge()
        self.pages["alerts"].request_refresh()

    def refresh_all(self) -> None:
        self.run_alerts(notify=False)
        for page in (*self.pages.values(), self.home):
            page.request_refresh()

    def _update_badge(self) -> None:
        total = self.ctx.alerts.unread_count()  # tous les espaces
        n = self.ctx.alerts.unread_count(space_id=CURRENT) if self.ctx.scope.space_id else total
        self.nav_buttons["alerts"].setText("🔔  Alertes" + (f"   ({n})" if n else ""))
        self.setWindowTitle(f"{'(%d) ' % total if total else ''}{APP_NAME} {__version__}")
        self.tray.setToolTip(f"{APP_NAME} — {total} alerte(s) non lue(s)" if total else APP_NAME)

    def _settings_changed(self) -> None:
        self.timer.start(int(self.ctx.settings.get("check_interval_seconds")) * 1000)
        self.refresh_all()

    # ------------------------------------------------------------------ alertes & notifications
    def run_alerts(self, notify: bool = True) -> None:
        try:
            fresh = self.ctx.alerts.run()
        except Exception:
            log.exception("Échec du calcul des alertes")
            return
        self._update_badge()
        if not fresh or not notify:
            return
        s = self.ctx.settings
        if s.get("native_notifications") and QSystemTrayIcon.supportsMessages() and self.tray.isVisible():
            limit = int(s.get("max_toasts_per_check"))
            if len(fresh) > limit:  # beaucoup d'alertes d'un coup : un seul message de synthèse
                crit = sum(1 for a in fresh if a.level == "critical")
                self.tray.showMessage(APP_NAME, f"{len(fresh)} nouvelle(s) alerte(s) dont {crit} critique(s). Cliquez pour les consulter.",
                                      QSystemTrayIcon.Warning, 12000)
            else:
                for a in fresh:
                    icon = QSystemTrayIcon.Critical if a.level == "critical" else QSystemTrayIcon.Warning
                    self.tray.showMessage(f"{a.space_name} · {LEVELS[a.level]} · {a.task_title[:60]}", a.message, icon, 12000)
        self.ctx.alerts.mark_notified([a.id for a in fresh])  # jamais renotifiées, même après redémarrage

    def tick(self) -> None:
        """Vérification périodique : changement de jour, alertes, sauvegarde automatique."""
        if self._closed:
            return
        now = self.ctx.clock()
        if now.date() != self._last_day:
            self._last_day = now.date()
            self.refresh_all()
        self.run_alerts(notify=True)
        if self.stack.currentWidget() in (self.pages["planning"], self.pages["dashboard"]):
            self.stack.currentWidget().refresh()
        try:
            self.ctx.backups.auto_if_due()
        except Exception:
            log.exception("Sauvegarde automatique impossible")

    # ------------------------------------------------------------------ fenêtre / fermeture
    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if (not self._quitting and self.ctx.settings.get("minimize_to_tray") and self.tray.isVisible()):
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(APP_NAME, "L'application reste active dans la zone de notification pour vous alerter. "
                                      "Clic droit sur l'icône > Quitter pour fermer.", QSystemTrayIcon.Information, 6000)
            return
        self._shutdown()
        e.accept()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()
        QApplication.quit()

    def _shutdown(self) -> None:
        self._closed = True
        self.timer.stop()
        self._coalesce.stop()
        try:
            if self.ctx.settings.get("backup_auto"):
                self.ctx.backups.auto_if_due()
        except Exception:
            log.exception("Sauvegarde à la fermeture impossible")
        self.tray.hide()
        self.ctx.close()

