"""Briques d'interface partagées : page de base, champs date/heure facultatifs, messages, formatage."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from PySide6.QtCore import QDate, QTime, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTimeEdit, QVBoxLayout, QWidget,
)

from ..core import rules
from ..core.models import Task, ValidationError


def fmt_date(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def fmt_dt(d: Optional[datetime]) -> str:
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


def due_text(t: Task, today: date) -> str:
    """Libellé court d'échéance : « En retard 5 j », « Aujourd'hui », « Dans 3 j »."""
    if t.is_closed or t.deadline is None:
        return ""
    left = (t.deadline - today).days
    if left < 0:
        return f"En retard de {-left} j"
    if left == 0:
        return "Aujourd'hui"
    return "Demain" if left == 1 else f"Dans {left} j"


def show_error(parent, exc: Exception, title: str = "Action impossible") -> None:
    if isinstance(exc, ValidationError):
        QMessageBox.warning(parent, title, str(exc))
    else:
        QMessageBox.critical(parent, title, f"{exc}\n\nDétails techniques dans le fichier journal de l'application.")


def confirm(parent, title: str, text: str, yes: str = "Confirmer", danger: bool = False) -> bool:
    box = QMessageBox(QMessageBox.Warning if danger else QMessageBox.Question, title, text, QMessageBox.NoButton, parent)
    ok = box.addButton(yes, QMessageBox.AcceptRole)
    box.addButton("Annuler", QMessageBox.RejectRole)
    box.setDefaultButton(box.buttons()[-1])
    box.exec()
    return box.clickedButton() is ok


class Card(QFrame):
    """Conteneur blanc arrondi avec titre optionnel."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 12)
        self.lay.setSpacing(8)
        if title:
            lab = QLabel(title)
            lab.setObjectName("sectionTitle")
            self.lay.addWidget(lab)
        self.title_label = lab if title else None


class Page(QWidget):
    """Page de l'application : se rafraîchit à l'affichage si les données ont changé entre-temps."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._dirty = True

    def refresh(self) -> None:  # à surcharger
        pass

    def request_refresh(self) -> None:
        if self.isVisible():
            self._dirty = False
            self.refresh()
        else:
            self._dirty = True

    def showEvent(self, e):
        super().showEvent(e)
        if self._dirty:
            self._dirty = False
            self.refresh()


def page_header(title: str, subtitle: str = "") -> tuple[QWidget, QHBoxLayout, QLabel]:
    w = QWidget()
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    row = QHBoxLayout()
    t = QLabel(title)
    t.setObjectName("pageTitle")
    row.addWidget(t)
    row.addStretch()
    outer.addLayout(row)
    sub = QLabel(subtitle)
    sub.setObjectName("muted")
    outer.addWidget(sub)
    return w, row, sub


class OptDate(QWidget):
    """Date facultative : case à cocher + sélecteur de date."""

    changed = Signal()

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox(label)
        self.edit = QDateEdit(QDate.currentDate())
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("dd/MM/yyyy")
        self.edit.setEnabled(False)
        lay.addWidget(self.check)
        lay.addWidget(self.edit, 1)
        self.check.toggled.connect(self._toggle)
        self.edit.dateChanged.connect(lambda *_: self.changed.emit())

    def _toggle(self, on: bool) -> None:
        self.edit.setEnabled(on)
        self.changed.emit()

    def value(self) -> Optional[date]:
        return self.edit.date().toPython() if self.check.isChecked() else None

    def set_value(self, d: Optional[date]) -> None:
        self.check.setChecked(d is not None)
        if d is not None:
            self.edit.setDate(QDate(d.year, d.month, d.day))


class OptTime(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox()
        self.edit = QTimeEdit(QTime(9, 0))
        self.edit.setDisplayFormat("HH:mm")
        self.edit.setEnabled(False)
        lay.addWidget(self.check)
        lay.addWidget(self.edit, 1)
        self.check.toggled.connect(lambda on: (self.edit.setEnabled(on), self.changed.emit()))

    def value(self) -> Optional[time]:
        return self.edit.time().toPython() if self.check.isChecked() else None

    def set_value(self, t: Optional[time]) -> None:
        self.check.setChecked(t is not None)
        if t is not None:
            self.edit.setTime(QTime(t.hour, t.minute))


def debounce(ms: int, fn) -> QTimer:
    timer = QTimer()
    timer.setSingleShot(True)
    timer.setInterval(ms)
    timer.timeout.connect(fn)
    return timer
