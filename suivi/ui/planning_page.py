"""Planning visuel jour / semaine : blocs horaires, chevauchements, créneaux libres, glisser-déposer."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from PySide6.QtCore import QDate, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QCalendarWidget, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..core import planning
from ..core.models import to_date
from . import theme
from .common import Card, Page, fmt_date, show_error
from .task_dialog import TaskDialog

DAYS_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
GUTTER, HOUR_H, SNAP = 52, 46, 15


class DayHeader(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(46)
        self.days: list[date] = []
        self.loads: dict[date, int] = {}
        self.today = date.today()

    def set_data(self, days, loads, today):
        self.days, self.loads, self.today = days, loads, today
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = max(1, len(self.days))
        w = (self.width() - GUTTER) / n
        for i, d in enumerate(self.days):
            r = QRectF(GUTTER + i * w, 0, w, self.height())
            is_today = d == self.today
            if is_today:
                p.fillRect(r.adjusted(2, 2, -2, 0), QColor("#DBE7FF"))
            p.setPen(QColor(theme.ACCENT if is_today else theme.TEXT))
            f = QFont(self.font()); f.setBold(True); p.setFont(f)
            p.drawText(QRectF(r.left(), 4, r.width(), 20), Qt.AlignCenter, f"{DAYS_FR[d.weekday()]} {d:%d/%m}")
            f.setBold(False); f.setPointSizeF(8.5); p.setFont(f)
            mins = self.loads.get(d, 0)
            p.setPen(QColor(theme.DANGER if mins > 8 * 60 else theme.MUTED))
            p.drawText(QRectF(r.left(), 24, r.width(), 18), Qt.AlignCenter,
                       f"{mins // 60} h {mins % 60:02d} planifiées" if mins else "libre")
        p.setPen(QPen(QColor(theme.BORDER)))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class TimeGrid(QWidget):
    open_task = Signal(int)
    create_at = Signal(object, object)  # (date, time)
    schedule_changed = Signal(int, object, object, object)  # (id, date, début, fin)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.days: list[date] = []
        self.blocks: dict[date, list[planning.Block]] = {}
        self.free: dict[date, list] = {}
        self.h0, self.h1 = 7, 20
        self.now = datetime.now()
        self._rects: list[tuple[QRectF, planning.Block]] = []
        self._drag = None  # (block, mode, offset_min, ghost)
        self._update_size()

    def _update_size(self):
        self.setMinimumHeight((self.h1 - self.h0) * HOUR_H + 2)

    def set_data(self, days, blocks, free, h0, h1, now):
        self.days, self.blocks, self.free, self.h0, self.h1, self.now = days, blocks, free, h0, h1, now
        self._update_size()
        self.update()

    # --- géométrie --------------------------------------------------------------------
    def _col_w(self) -> float:
        return (self.width() - GUTTER) / max(1, len(self.days))

    def _y(self, dt_or_time) -> float:
        t = dt_or_time.time() if isinstance(dt_or_time, datetime) else dt_or_time
        return ((t.hour * 60 + t.minute) / 60 - self.h0) * HOUR_H

    def _pos_to_slot(self, x: float, y: float):
        n = len(self.days)
        if n == 0:
            return None
        col = min(n - 1, max(0, int((x - GUTTER) // self._col_w())))
        minutes = int(round(((y / HOUR_H) + self.h0) * 60 / SNAP)) * SNAP
        return self.days[col], max(0, min(24 * 60 - SNAP, minutes))

    # --- dessin -----------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        n = max(1, len(self.days))
        w = self._col_w()
        # créneaux libres (teinte verte discrète) + colonne d'aujourd'hui
        for i, d in enumerate(self.days):
            x = GUTTER + i * w
            if d == self.now.date():
                p.fillRect(QRectF(x, 0, w, self.height()), QColor("#F5F9FF"))
            for a, b in self.free.get(d, []):
                p.fillRect(QRectF(x + 1, self._y(a), w - 2, self._y(b) - self._y(a)), QColor(22, 163, 74, 18))
        # grille horaire
        p.setPen(QPen(QColor("#E6EAF1"), 1))
        for h in range(self.h0, self.h1 + 1):
            y = (h - self.h0) * HOUR_H
            p.drawLine(GUTTER, int(y), self.width(), int(y))
            if h < self.h1:
                p.setPen(QColor(theme.MUTED))
                p.drawText(QRectF(0, y + 2, GUTTER - 6, 16), Qt.AlignRight, f"{h:02d}:00")
                p.setPen(QPen(QColor("#E6EAF1"), 1))
                p.setPen(QPen(QColor("#F0F3F8"), 1, Qt.DotLine))
                p.drawLine(GUTTER, int(y + HOUR_H / 2), self.width(), int(y + HOUR_H / 2))
                p.setPen(QPen(QColor("#E6EAF1"), 1))
        for i in range(n + 1):
            x = GUTTER + i * w
            p.drawLine(int(x), 0, int(x), self.height())
        # blocs
        self._rects = []
        fm = QFontMetrics(self.font())
        for i, d in enumerate(self.days):
            for b in self.blocks.get(d, []):
                r = self._block_rect(b, i, w)
                self._rects.append((r, b))
                self._paint_block(p, b, r, fm)
        # ligne « maintenant »
        for i, d in enumerate(self.days):
            if d == self.now.date() and self.h0 <= self.now.hour < self.h1:
                y = self._y(self.now)
                p.setPen(QPen(QColor(theme.DANGER), 2))
                p.drawLine(int(GUTTER + i * w), int(y), int(GUTTER + (i + 1) * w), int(y))
                p.setBrush(QColor(theme.DANGER)); p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(GUTTER + i * w, y), 4, 4)
        if self._drag and self._drag[3]:
            r = self._drag[3]
            p.setPen(QPen(QColor(theme.ACCENT), 2, Qt.DashLine))
            p.setBrush(QColor(37, 99, 235, 40))
            p.drawRoundedRect(r, 5, 5)

    def _block_rect(self, b: planning.Block, col: int, w: float) -> QRectF:
        sub = w / max(1, b.columns)
        top = self._y(b.start)
        bottom = self._y(b.end)
        return QRectF(GUTTER + col * w + b.column * sub + 2, top + 1, sub - 4, max(18, bottom - top - 2))

    def _paint_block(self, p: QPainter, b: planning.Block, r: QRectF, fm: QFontMetrics) -> None:
        t = b.task
        base = QColor(t.project_color or t.status_color)
        closed = t.is_closed
        fill = QColor(base); fill.setAlpha(60 if closed else 215)
        p.setBrush(fill)
        p.setPen(QPen(QColor(theme.DANGER), 2) if b.overlaps else QPen(base.darker(115), 1))
        p.drawRoundedRect(r, 5, 5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.PRIORITY_COLORS[t.priority]))
        p.drawRoundedRect(QRectF(r.left(), r.top(), 4, r.height()), 2, 2)
        p.setPen(QColor(theme.TEXT) if closed else theme.contrast_text(base.name()))
        f = QFont(self.font()); f.setPointSizeF(8.5); f.setStrikeOut(closed); p.setFont(f)
        flag = "⚠ " if b.overlaps else ""
        text = f"{flag}{b.start:%H:%M}–{b.end:%H:%M}  {t.title}"
        p.drawText(r.adjusted(9, 2, -3, -2), Qt.AlignTop | Qt.TextWordWrap, text)
        p.setFont(self.font())

    # --- interaction ------------------------------------------------------------------
    def _block_at(self, pos) -> Optional[tuple[QRectF, planning.Block]]:
        for r, b in reversed(self._rects):
            if r.contains(pos):
                return r, b
        return None

    def mouseDoubleClickEvent(self, e):
        hit = self._block_at(e.position())
        if hit:
            return self.open_task.emit(hit[1].task.id)
        slot = self._pos_to_slot(e.position().x(), e.position().y())
        if slot and e.position().x() > GUTTER:
            self.create_at.emit(slot[0], time(slot[1] // 60, slot[1] % 60))

    def mousePressEvent(self, e):
        hit = self._block_at(e.position())
        if hit and e.button() == Qt.LeftButton:
            r, b = hit
            mode = "resize" if e.position().y() > r.bottom() - 7 else "move"
            self._drag = [b, mode, (e.position().y() - r.top()), None]

    def mouseMoveEvent(self, e):
        pos = e.position()
        if not self._drag:
            hit = self._block_at(pos)
            if hit:
                self.setCursor(Qt.SizeVerCursor if pos.y() > hit[0].bottom() - 7 else Qt.OpenHandCursor)
                b = hit[1]
                self.setToolTip(f"{b.task.title}\n{b.start:%H:%M} – {b.end:%H:%M} · {b.task.status_label}\n"
                                f"Projet : {b.task.project_name or '—'}" + ("\n⚠ Chevauchement" if b.overlaps else ""))
            else:
                self.setCursor(Qt.ArrowCursor); self.setToolTip("")
            return
        b, mode, off, _ = self._drag
        slot = self._pos_to_slot(pos.x(), pos.y() - (off if mode == "move" else 0))
        if not slot:
            return
        day, minutes = slot
        col = self.days.index(day)
        w = self._col_w()
        if mode == "move":
            top = self._y(time(minutes // 60, minutes % 60))
            height = (b.end - b.start).total_seconds() / 3600 * HOUR_H
            self._drag[3] = QRectF(GUTTER + col * w + 2, top, w - 4, height)
        else:
            start_min = b.start.hour * 60 + b.start.minute
            end_min = max(start_min + SNAP, minutes + (SNAP if minutes <= start_min else 0))
            col = self.days.index(b.start.date())
            self._drag[3] = QRectF(GUTTER + col * w + 2, self._y(b.start), w - 4, (end_min - start_min) / 60 * HOUR_H)
        self.update()

    def mouseReleaseEvent(self, e):
        if not self._drag:
            return
        b, mode, off, ghost = self._drag
        self._drag = None
        self.update()
        if ghost is None:  # simple clic
            return
        pos = e.position()
        slot = self._pos_to_slot(pos.x(), pos.y() - (off if mode == "move" else 0))
        if not slot:
            return
        day, minutes = slot
        dur = int((b.end - b.start).total_seconds() // 60)
        if mode == "move":
            start_m = minutes
            end_m = min(24 * 60 - 1, start_m + dur)
            day_new = day
        else:
            start_m = b.start.hour * 60 + b.start.minute
            end_m = max(start_m + SNAP, minutes if minutes > start_m else start_m + SNAP)
            end_m = min(end_m, 24 * 60 - 1)
            day_new = b.start.date()
        if (day_new, start_m, end_m) == (b.start.date(), b.start.hour * 60 + b.start.minute, b.start.hour * 60 + b.start.minute + dur):
            return
        self.schedule_changed.emit(b.task.id, day_new, time(start_m // 60, start_m % 60), time(end_m // 60, end_m % 60))


class PlanningPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.anchor = ctx.clock().date()
        self.mode = "week"
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(14)

        # --- colonne principale
        main = QVBoxLayout()
        title = QLabel("Calendrier et planning"); title.setObjectName("pageTitle")
        main.addWidget(title)
        bar = QHBoxLayout()
        prev, nxt, today = QPushButton("◀"), QPushButton("▶"), QPushButton("Aujourd'hui")
        prev.clicked.connect(lambda: self.shift(-1)); nxt.clicked.connect(lambda: self.shift(1))
        today.clicked.connect(lambda: self.set_anchor(self.ctx.clock().date()))
        self.range_label = QLabel(); self.range_label.setStyleSheet("font-size:12pt;font-weight:600;")
        self.b_day, self.b_week = QPushButton("Jour"), QPushButton("Semaine")
        for b in (self.b_day, self.b_week):
            b.setCheckable(True)
        self.b_week.setChecked(True)
        group = QButtonGroup(self); group.setExclusive(True); group.addButton(self.b_day); group.addButton(self.b_week)
        self.b_day.clicked.connect(lambda: self.set_mode("day")); self.b_week.clicked.connect(lambda: self.set_mode("week"))
        new = QPushButton("＋ Planifier une tâche"); new.setObjectName("primary"); new.clicked.connect(self._new)
        for w in (prev, today, nxt):
            bar.addWidget(w)
        bar.addWidget(self.range_label); bar.addStretch(); bar.addWidget(self.b_day); bar.addWidget(self.b_week); bar.addWidget(new)
        main.addLayout(bar)
        self.header = DayHeader()
        self.grid = TimeGrid()
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setWidget(self.grid)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setStyleSheet("QScrollArea{border:1px solid %s;background:white;}" % theme.BORDER)
        sb = self.scroll.verticalScrollBar().sizeHint().width() + 2
        hbox = QHBoxLayout(); hbox.setContentsMargins(0, 0, sb, 0); hbox.addWidget(self.header)
        main.addLayout(hbox)
        main.addWidget(self.scroll, 1)
        root.addLayout(main, 1)
        self.grid.open_task.connect(lambda i: TaskDialog(self.ctx, i, None, self).exec())
        self.grid.create_at.connect(self._create_at)
        self.grid.schedule_changed.connect(self._reschedule)

        # --- panneau latéral
        side = QVBoxLayout()
        side.setSpacing(10)
        self.cal = QCalendarWidget(); self.cal.setGridVisible(False); self.cal.setFirstDayOfWeek(Qt.Monday)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.cal.clicked.connect(lambda qd: self.set_anchor(qd.toPython()))
        side.addWidget(self.cal)
        self.alerts_card = Card("À surveiller"); self.watch = QLabel(); self.watch.setWordWrap(True)
        self.alerts_card.lay.addWidget(self.watch); side.addWidget(self.alerts_card)
        free = Card("Créneaux libres (jour sélectionné)"); self.free_list = QListWidget(); self.free_list.setMaximumHeight(110)
        free.lay.addWidget(self.free_list); side.addWidget(free)
        uns = Card("Tâches sans horaire"); self.uns_list = QListWidget()
        self.uns_list.itemDoubleClicked.connect(lambda it: TaskDialog(self.ctx, it.data(Qt.UserRole), None, self).exec())
        uns.lay.addWidget(self.uns_list); side.addWidget(uns, 1)
        sidew = QWidget(); sidew.setLayout(side); sidew.setFixedWidth(290)
        root.addWidget(sidew)

    # ------------------------------------------------------------------ navigation
    def days(self) -> list[date]:
        if self.mode == "day":
            return [self.anchor]
        ws = planning.week_start(self.anchor)
        return [ws + timedelta(days=i) for i in range(7)]

    def set_anchor(self, d: date) -> None:
        self.anchor = d
        self.refresh()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.refresh()

    def shift(self, n: int) -> None:
        self.anchor += timedelta(days=n * (1 if self.mode == "day" else 7))
        self.refresh()

    # ------------------------------------------------------------------ données
    def refresh(self) -> None:
        now = self.ctx.clock()
        s = self.ctx.settings
        tasks = self.ctx.tasks.all()
        days = self.days()
        h0 = max(0, int(s.get("work_start_hour")) - 1)
        h1 = min(24, int(s.get("work_end_hour")) + 1)
        blocks = {d: planning.blocks_for_day(tasks, d) for d in days}
        # élargit la plage si une tâche sort des heures de travail
        for bl in blocks.values():
            for b in bl:
                h0 = min(h0, b.start.hour)
                h1 = max(h1, min(24, b.end.hour + (1 if b.end.minute else 0)))
        free = {d: planning.free_slots(blocks[d], d, int(s.get("work_start_hour")), int(s.get("work_end_hour")),
                                       int(s.get("min_free_slot_minutes"))) for d in days}
        loads = {d: planning.busy_minutes(blocks[d]) for d in days}
        self.grid.set_data(days, blocks, free, h0, h1, now)
        self.header.set_data(days, loads, now.date())
        self.range_label.setText(f"{days[0]:%d/%m/%Y}" if len(days) == 1 else f"{days[0]:%d/%m} – {days[-1]:%d/%m/%Y}")
        self.cal.setSelectedDate(QDate(self.anchor.year, self.anchor.month, self.anchor.day))

        self.free_list.clear()
        for a, b in free.get(self.anchor, free[days[0]] if self.mode == "week" and self.anchor not in free else []):
            self.free_list.addItem(f"{a:%H:%M} – {b:%H:%M}   ({int((b - a).total_seconds() // 60)} min)")
        if not self.free_list.count():
            self.free_list.addItem("Aucun créneau libre")

        self.uns_list.clear()
        for d in days:
            for t in planning.unscheduled(tasks, d):
                it = QListWidgetItem(f"{d:%a %d/%m} · {t.title}")
                it.setData(Qt.UserRole, t.id)
                self.uns_list.addItem(it)
        if not self.uns_list.count():
            self.uns_list.addItem("Aucune")

        notes = []
        n_over = sum(len(planning.find_overlaps(b)) for b in blocks.values())
        if n_over:
            notes.append(f"⚠ {n_over} chevauchement(s) sur la période.")
        forgotten = planning.forgotten(tasks, now)
        if forgotten:
            notes.append(f"🕘 {len(forgotten)} tâche(s) planifiée(s) non démarrée(s) : " + ", ".join(t.title[:28] for t in forgotten[:3]))
        late = planning.ended_late(tasks, now)
        if late:
            notes.append(f"⏰ {len(late)} tâche(s) dont l'heure de fin est dépassée : " + ", ".join(t.title[:28] for t in late[:3]))
        self.watch.setText("\n\n".join(notes) or "✔ Rien à signaler.")

    # ------------------------------------------------------------------ actions
    def _new(self) -> None:
        TaskDialog(self.ctx, None, {"start_date": self.anchor, "start_time": time(9, 0), "end_time": time(10, 0)}, self).exec()

    def _create_at(self, day: date, t: time) -> None:
        end = (datetime.combine(day, t) + timedelta(hours=1)).time()
        TaskDialog(self.ctx, None, {"start_date": day, "start_time": t, "end_time": end}, self).exec()

    def _reschedule(self, task_id: int, day: date, start: time, end: time) -> None:
        try:
            self.ctx.tasks.set_schedule(task_id, day, start, end)
        except Exception as exc:
            show_error(self, exc)
            self.refresh()
