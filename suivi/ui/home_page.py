"""Page d'accueil : sobre, aérée, avec des tuiles pour chaque espace et module."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..core import rules
from ..modules import enabled_modules
from .common import Page

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class Tile(QFrame):
    clicked = Signal()

    def __init__(self, icon: str, title: str, lines: list[tuple[str, str]], color: str, clickable: bool = True, dashed: bool = False):
        super().__init__()
        self.setObjectName("tileDashed" if dashed else "tile")
        self.setMinimumSize(250, 170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(180)
        self._clickable = clickable
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(2)
        badge = QLabel(icon)
        badge.setFixedSize(52, 52)
        badge.setAlignment(Qt.AlignCenter)
        q = QColor(color)  # (Qt lit #RRGGBBAA comme #AARRGGBB : on passe par rgba())
        badge.setStyleSheet(f"background: rgba({q.red()},{q.green()},{q.blue()},0.14); color:{color}; border-radius:26px; font-size:22pt;")
        lay.addWidget(badge)
        lay.addSpacing(8)
        t = QLabel(title)
        t.setStyleSheet("font-size:15pt; font-weight:600; background:transparent;")
        lay.addWidget(t)
        for text, css in lines:
            l = QLabel(text)
            l.setStyleSheet(f"background:transparent; {css}")
            lay.addWidget(l)
        lay.addStretch()

    def mousePressEvent(self, e):
        if self._clickable and e.button() == Qt.LeftButton:
            self.clicked.emit()


class HomePage(Page):
    open_space = Signal(int)
    open_settings = Signal()
    open_alerts = Signal()
    open_module = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.setObjectName("home")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget(); body.setObjectName("homeBody"); scroll.setWidget(body)
        wrap = QHBoxLayout(body)
        wrap.setContentsMargins(40, 28, 40, 40)
        wrap.addStretch(1)
        col = QWidget(); col.setMaximumWidth(1020); col.setMinimumWidth(560)
        col.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        wrap.addWidget(col, 100)
        wrap.addStretch(1)
        self.col = QVBoxLayout(col)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(6)

        top = QHBoxLayout()
        brand = QLabel("Suivi"); brand.setStyleSheet("font-size:11pt; font-weight:600; color:#86868B;")
        top.addWidget(brand); top.addStretch()
        self.bell = QPushButton("🔔"); self.bell.setObjectName("homeBtn"); self.bell.setCursor(Qt.PointingHandCursor)
        self.bell.clicked.connect(self.open_alerts)
        gear = QPushButton("⚙  Réglages"); gear.setObjectName("homeBtn"); gear.setCursor(Qt.PointingHandCursor)
        gear.clicked.connect(self.open_settings)
        top.addWidget(self.bell); top.addWidget(gear)
        self.col.addLayout(top)
        self.col.addSpacing(26)

        self.hello = QLabel(); self.hello.setStyleSheet("font-size:30pt; font-weight:700; color:#1D1D1F;")
        self.date = QLabel(); self.date.setStyleSheet("font-size:13pt; color:#86868B;")
        self.col.addWidget(self.hello); self.col.addWidget(self.date)
        self.col.addSpacing(30)

        self.sec1 = QLabel("Espaces"); self.sec1.setStyleSheet("font-size:12pt; font-weight:600; color:#1D1D1F;")
        self.col.addWidget(self.sec1)
        self.grid1 = QGridLayout(); self.grid1.setSpacing(18)
        self.col.addLayout(self.grid1)
        self.col.addSpacing(26)
        self.sec2 = QLabel("Applications"); self.sec2.setStyleSheet("font-size:12pt; font-weight:600; color:#1D1D1F;")
        self.col.addWidget(self.sec2)
        self.grid2 = QGridLayout(); self.grid2.setSpacing(18)
        self.col.addLayout(self.grid2)
        self.col.addStretch(1)

    @staticmethod
    def _clear(grid: QGridLayout) -> None:
        while grid.count():
            w = grid.takeAt(0).widget()
            if w:
                w.setParent(None)  # retiré tout de suite (sinon il reste affiché jusqu'au prochain tour d'événements)
                w.deleteLater()

    def refresh(self) -> None:
        now = self.ctx.clock()
        today = now.date()
        h = now.hour
        self.hello.setText("Bonjour" if h < 18 else "Bonsoir")
        self.date.setText(f"{DAYS[today.weekday()].capitalize()} {today.day} {MONTHS[today.month - 1]} {today.year}")
        unread = self.ctx.alerts.unread_count()
        self.bell.setText(f"🔔  {unread}" if unread else "🔔")
        self.bell.setToolTip(f"{unread} alerte(s) non lue(s)" if unread else "Aucune alerte non lue")

        self._clear(self.grid1)
        cols = 3
        spaces = self.ctx.spaces.list(enabled_only=True)
        all_tasks = self.ctx.tasks.all(space_id=None)
        for i, sp in enumerate(spaces):
            mine = [t for t in all_tasks if t.space_id == sp.id]
            active = [t for t in mine if t.is_active]
            late = sum(1 for t in active if rules.is_overdue(t, today))
            due = sum(1 for t in active if rules.is_due_today(t, today))
            lines = [(f"{len(active)} tâche(s) ouverte(s)", "font-size:10.5pt; color:#6E6E73;")]
            if late:
                lines.append((f"{late} en retard", "font-size:10.5pt; color:#D70015; font-weight:600;"))
            elif due:
                lines.append((f"{due} pour aujourd'hui", "font-size:10.5pt; color:#C93400;"))
            else:
                lines.append(("Tout est à jour" if active else "Rien en cours", "font-size:10.5pt; color:#248A3D;"))
            tile = Tile(sp.icon, sp.name, lines, sp.color)
            tile.clicked.connect(lambda sid=sp.id: self.open_space.emit(sid))
            self.grid1.addWidget(tile, i // cols, i % cols)
        add = Tile("＋", "Nouvel espace", [("Ajouter un espace de tâches", "font-size:10.5pt; color:#86868B;")], "#86868B", dashed=True)
        add.clicked.connect(self.open_settings)
        n = len(spaces)
        self.grid1.addWidget(add, n // cols, n % cols)
        for c in range(cols):
            self.grid1.setColumnStretch(c, 1)

        self._clear(self.grid2)
        mods = enabled_modules(self.ctx.settings)
        self.sec2.setVisible(True)
        for i, m in enumerate(mods):
            lines = [(m.description, "font-size:10.5pt; color:#6E6E73;")]
            if not m.available:
                lines.append(("Bientôt disponible", "font-size:10.5pt; color:#86868B; font-style:italic;"))
            tile = Tile(m.icon, m.label, lines, "#0891B2", clickable=m.available)
            tile.clicked.connect(lambda k=m.key: self.open_module.emit(k))
            self.grid2.addWidget(tile, i // cols, i % cols)
        more = Tile("⊞", "Ajouter une application", [("Activer des modules dans les réglages", "font-size:10.5pt; color:#86868B;")],
                    "#86868B", dashed=True)
        more.clicked.connect(self.open_settings)
        k = len(mods)
        self.grid2.addWidget(more, k // cols, k % cols)
        for c in range(cols):
            self.grid2.setColumnStretch(c, 1)
