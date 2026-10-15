"""Graphiques légers dessinés avec QPainter (aucune dépendance externe, thème cohérent)."""
from __future__ import annotations

import math
from typing import Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from . import theme

Item = tuple  # (libellé, valeur, couleur[, info-bulle])


class _Chart(QWidget):
    clicked = Signal(str)

    def __init__(self, empty_text: str = "Aucune donnée à afficher", parent=None):
        super().__init__(parent)
        self.empty_text = empty_text
        self._hits: list[tuple[QRectF, str, str]] = []  # (zone, libellé, info-bulle)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(190)

    # --- interaction ---------------------------------------------------------------
    def _hit(self, pos) -> Optional[tuple[QRectF, str, str]]:
        for r in self._hits:
            if r[0].contains(pos):
                return r
        return None

    def mouseMoveEvent(self, e):
        h = self._hit(e.position())
        self.setCursor(Qt.PointingHandCursor if h and h[1] else Qt.ArrowCursor)
        if h and h[2]:
            QToolTip.showText(e.globalPosition().toPoint(), h[2], self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, e):
        h = self._hit(e.position())
        if h and h[1]:
            self.clicked.emit(h[1])

    def _paint_empty(self, p: QPainter) -> None:
        p.setPen(QColor(theme.MUTED))
        p.drawText(self.rect(), Qt.AlignCenter, self.empty_text)

    def _begin(self) -> QPainter:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._hits = []
        return p


class HBarChart(_Chart):
    """Barres horizontales (classements)."""

    def __init__(self, parent=None, **kw):
        super().__init__(parent=parent, **kw)
        self.items: list[Item] = []
        self.show_values = True

    def set_data(self, items: Sequence[Item]) -> None:
        self.items = [i for i in items]
        self.setMinimumHeight(max(190, 30 * len(self.items) + 16))
        self.update()

    def paintEvent(self, _):
        p = self._begin()
        if not self.items:
            return self._paint_empty(p)
        fm = QFontMetrics(self.font())
        label_w = min(170, max(fm.horizontalAdvance(i[0]) for i in self.items) + 10)
        val_w = 46
        top, row_h = 4, max(24, (self.height() - 8) / len(self.items))
        peak = max(1, max(i[1] for i in self.items))
        bar_x, bar_max = label_w + 8, max(10, self.width() - label_w - val_w - 16)
        for k, it in enumerate(self.items):
            label, value, color = it[0], it[1], it[2]
            y = top + k * row_h
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(0, y, label_w, row_h), Qt.AlignVCenter | Qt.AlignRight, fm.elidedText(label, Qt.ElideRight, int(label_w)))
            w = bar_max * value / peak
            rect = QRectF(bar_x, y + row_h * 0.2, max(w, 2 if value else 0), row_h * 0.6)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(rect, 4, 4)
            if self.show_values:
                p.setPen(QColor(theme.MUTED))
                p.drawText(QRectF(rect.right() + 6, y, val_w + 20, row_h), Qt.AlignVCenter | Qt.AlignLeft, f"{value:g}")
            tip = it[3] if len(it) > 3 else f"{label} : {value:g}"
            self._hits.append((QRectF(0, y, self.width(), row_h), label, tip))


class ColumnChart(_Chart):
    """Histogramme vertical."""

    def __init__(self, parent=None, **kw):
        super().__init__(parent=parent, **kw)
        self.items: list[Item] = []
        self.color = theme.ACCENT

    def set_data(self, items: Sequence[Item]) -> None:
        self.items = list(items)
        self.update()

    def paintEvent(self, _):
        p = self._begin()
        if not self.items or all(i[1] == 0 for i in self.items):
            return self._paint_empty(p)
        left, bottom, top = 8, 22, 18
        plot_h = self.height() - bottom - top
        n = len(self.items)
        slot = (self.width() - left * 2) / n
        peak = max(i[1] for i in self.items) or 1
        p.setPen(QPen(QColor("#E6EAF1"), 1))
        for frac in (0.25, 0.5, 0.75, 1.0):
            y = top + plot_h * (1 - frac)
            p.drawLine(left, int(y), self.width() - left, int(y))
        for k, it in enumerate(self.items):
            label, value = it[0], it[1]
            color = it[2] if len(it) > 2 and it[2] else self.color
            h = plot_h * value / peak
            x = left + k * slot
            rect = QRectF(x + slot * 0.2, top + plot_h - h, slot * 0.6, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            if value:
                p.drawRoundedRect(rect, 3, 3)
                p.setPen(QColor(theme.TEXT))
                p.drawText(QRectF(x, rect.top() - 16, slot, 15), Qt.AlignCenter, f"{value:g}")
            p.setPen(QColor(theme.MUTED))
            f = QFont(self.font()); f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5)); p.setFont(f)
            p.drawText(QRectF(x, self.height() - bottom + 4, slot, bottom - 4), Qt.AlignHCenter | Qt.AlignTop, label)
            p.setFont(self.font())
            tip = it[3] if len(it) > 3 else f"{label} : {value:g}"
            self._hits.append((QRectF(x, top, slot, plot_h + bottom), "", tip))


class DonutChart(_Chart):
    def __init__(self, parent=None, **kw):
        super().__init__(parent=parent, **kw)
        self.items: list[Item] = []
        self.center_text = ""

    def set_data(self, items: Sequence[Item], center_text: str = "") -> None:
        self.items = [i for i in items if i[1] > 0]
        self.center_text = center_text
        self.update()

    def paintEvent(self, _):
        p = self._begin()
        total = sum(i[1] for i in self.items)
        if not total:
            return self._paint_empty(p)
        side = min(self.height() - 8, self.width() * 0.5)
        ring = QRectF(8, (self.height() - side) / 2, side, side)
        start = 90 * 16
        for it in self.items:
            span = -int(round(it[1] / total * 360 * 16))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(it[2]))
            p.drawPie(ring, start, span)
            start += span
        hole = ring.adjusted(side * 0.24, side * 0.24, -side * 0.24, -side * 0.24)
        p.setBrush(QColor(theme.CARD))
        p.drawEllipse(hole)
        p.setPen(QColor(theme.TEXT))
        f = QFont(self.font()); f.setPointSizeF(f.pointSizeF() + 6); f.setBold(True); p.setFont(f)
        p.drawText(hole, Qt.AlignCenter, self.center_text or f"{total:g}")
        p.setFont(self.font())
        # légende
        fm = QFontMetrics(self.font())
        x = ring.right() + 18
        row = 22
        y0 = max(4, (self.height() - row * min(len(self.items), 9)) / 2)
        for k, it in enumerate(self.items[:9]):
            y = y0 + k * row
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(it[2]))
            p.drawRoundedRect(QRectF(x, y + 5, 11, 11), 3, 3)
            p.setPen(QColor(theme.TEXT))
            txt = fm.elidedText(f"{it[0]}  ·  {it[1]:g} ({it[1] / total:.0%})", Qt.ElideRight, int(self.width() - x - 24))
            p.drawText(QRectF(x + 18, y, self.width() - x - 18, row), Qt.AlignVCenter, txt)
            self._hits.append((QRectF(x, y, self.width() - x, row), it[0], f"{it[0]} : {it[1]:g} ({it[1] / total:.1%})"))


class LineChart(_Chart):
    def __init__(self, parent=None, **kw):
        super().__init__(parent=parent, **kw)
        self.points: list[tuple[str, float]] = []
        self.color = theme.SUCCESS

    def set_data(self, points: Sequence[tuple[str, float]]) -> None:
        self.points = list(points)
        self.update()

    def paintEvent(self, _):
        p = self._begin()
        if not self.points or all(v == 0 for _, v in self.points):
            return self._paint_empty(p)
        left, right, top, bottom = 30, 12, 14, 24
        w, h = self.width() - left - right, self.height() - top - bottom
        peak = max(v for _, v in self.points) or 1
        peak = math.ceil(peak / 5) * 5 if peak > 5 else peak
        n = len(self.points)
        step = w / max(1, n - 1)
        p.setPen(QPen(QColor("#E6EAF1"), 1))
        for frac in (0, 0.5, 1):
            y = top + h * (1 - frac)
            p.drawLine(left, int(y), self.width() - right, int(y))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(0, y - 8, left - 4, 16), Qt.AlignRight | Qt.AlignVCenter, f"{peak * frac:g}")
            p.setPen(QPen(QColor("#E6EAF1"), 1))
        pts = [QPointF(left + i * step, top + h * (1 - v / peak)) for i, (_, v) in enumerate(self.points)]
        area = QPainterPath(QPointF(pts[0].x(), top + h))
        for pt in pts:
            area.lineTo(pt)
        area.lineTo(QPointF(pts[-1].x(), top + h))
        p.fillPath(area, QColor(self.color).lighter(185))
        p.setPen(QPen(QColor(self.color), 2.2))
        p.drawPolyline(pts)
        f = QFont(self.font()); f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5)); p.setFont(f)
        every = max(1, n // 8)
        for i, (pt, (lab, v)) in enumerate(zip(pts, self.points)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.color))
            p.drawEllipse(pt, 3.2, 3.2)
            if i % every == 0 or i == n - 1:
                p.setPen(QColor(theme.MUTED))
                p.drawText(QRectF(pt.x() - 24, self.height() - bottom + 4, 48, bottom), Qt.AlignHCenter | Qt.AlignTop, lab)
            self._hits.append((QRectF(pt.x() - step / 2, 0, max(step, 12), self.height()), "", f"{lab} : {v:g} terminée(s)"))
        p.setFont(self.font())
