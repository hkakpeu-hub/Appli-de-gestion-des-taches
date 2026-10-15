"""Thème visuel : couleurs, feuille de style Qt, utilitaires."""
from __future__ import annotations

from PySide6.QtGui import QColor

NAVY = "#14243D"
NAVY_HOVER = "#1E3557"
ACCENT = "#2563EB"
BG = "#F3F5F9"
CARD = "#FFFFFF"
BORDER = "#DDE3EC"
TEXT = "#1B2433"
MUTED = "#6B778C"
DANGER = "#DC2626"
WARNING = "#D97706"
SUCCESS = "#16A34A"

PRIORITY_COLORS = {"low": "#94A3B8", "normal": "#3B82F6", "high": "#F59E0B", "critical": "#DC2626"}


def qcolor(value: str, alpha: int = 255) -> QColor:
    c = QColor(value)
    c.setAlpha(alpha)
    return c


def contrast_text(bg: str) -> QColor:
    c = QColor(bg)
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return QColor("#111827") if lum > 170 else QColor("#FFFFFF")


STYLESHEET = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#content {{ background: {BG}; }}
QFrame#sidebar {{ background: {NAVY}; }}
QLabel#brand {{ color: white; font-size: 14pt; font-weight: 700; padding: 18px 16px 2px 16px; }}
QLabel#brandSub {{ color: #8FA3C2; padding: 0 16px 14px 16px; font-size: 8.5pt; }}
QPushButton#nav {{ background: transparent; color: #C9D6EC; border: none; text-align: left;
    padding: 10px 16px; font-size: 10.5pt; border-left: 3px solid transparent; }}
QPushButton#nav:hover {{ background: {NAVY_HOVER}; color: white; }}
QPushButton#nav:checked {{ background: {NAVY_HOVER}; color: white; font-weight: 600; border-left: 3px solid #60A5FA; }}
QLabel#pageTitle {{ font-size: 18pt; font-weight: 700; }}
QLabel#muted, QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel#sectionTitle {{ font-size: 11.5pt; font-weight: 600; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#card QLabel {{ background: transparent; }}
QFrame#kpi {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#kpi:hover {{ border-color: {ACCENT}; }}
QLabel#kpiValue {{ font-size: 24pt; font-weight: 700; background: transparent; }}
QLabel#kpiLabel {{ color: {MUTED}; background: transparent; }}
QPushButton {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #A0AAB8; background: #EEF1F6; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: #1D4ED8; }}
QPushButton#danger {{ color: {DANGER}; }}
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QTextEdit, QPlainTextEdit {{
    background: white; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QTableView, QTreeView, QListWidget {{ background: white; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: #EEF1F6; alternate-background-color: #FAFBFD; selection-background-color: #DBE7FF; selection-color: {TEXT}; }}
QHeaderView::section {{ background: #EEF2F8; border: none; border-bottom: 1px solid {BORDER}; padding: 7px 8px; font-weight: 600; color: #3B475C; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: white; top: -1px; }}
QTabBar::tab {{ padding: 8px 16px; background: transparent; border: none; color: {MUTED}; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #C5CDDA; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #C5CDDA; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ background: {NAVY}; color: white; border: none; padding: 5px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 12px; padding: 12px; background: white; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; font-weight: 600; }}
QWidget#homeBody, QWidget#home {{ background: #F5F5F7; }}
QFrame#tile {{ background: white; border: 1px solid #E5E5EA; border-radius: 22px; }}
QFrame#tile:hover {{ border: 1px solid #0A84FF; background: #FCFDFF; }}
QFrame#tileDashed {{ background: transparent; border: 1.5px dashed #C7C7CC; border-radius: 22px; }}
QFrame#tileDashed:hover {{ border-color: #0A84FF; }}
QPushButton#homeBtn {{ background: transparent; border: none; color: #0A66D6; font-size: 11pt; padding: 6px 12px; border-radius: 14px; }}
QPushButton#homeBtn:hover {{ background: #E8F0FE; }}
QStatusBar {{ background: white; border-top: 1px solid {BORDER}; }}
"""
