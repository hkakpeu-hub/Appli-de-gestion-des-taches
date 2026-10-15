"""Importation / exportation Excel, sauvegardes et restauration."""
from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import paths
from ..core.spaces import CURRENT
from ..core.tasks import TaskFilter
from ..excel.exporter import export_tasks
from ..excel.importer import ImportFailed, ImportPreview
from .common import Card, Page, confirm, fmt_dt, page_header, show_error

STATE_LABELS = {"new": "Nouvelle", "duplicate": "Doublon (ignorée)", "update": "Mise à jour", "invalid": "Rejetée"}
STATE_COLORS = {"new": "#166534", "duplicate": "#64748B", "update": "#1D4ED8", "invalid": "#B91C1C"}


class ImportDialog(QDialog):
    """Prévisualisation avant import : feuilles, doublons, lignes invalides, avertissements."""

    def __init__(self, ctx, path: Path, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(f"Importer — {path.name}")
        self.resize(1050, 700)
        self.preview: ImportPreview = ctx.importer.preview(path)
        self.report = None
        root = QVBoxLayout(self)

        root.addWidget(QLabel("<b>1. Feuilles à importer</b> (les feuilles sans colonnes « Action » et suivi sont ignorées) :"))
        self.sheets = QTableWidget(len(self.preview.sheets), 5)
        self.sheets.setHorizontalHeaderLabels(["Importer", "Feuille", "Lignes", "Espace de destination", "Projet par défaut (si pas de colonne Projet)"])
        self.sheets.verticalHeader().setVisible(False)
        self.sheets.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.sheets.horizontalHeader().setStretchLastSection(True)
        self.sheets.setMaximumHeight(34 + 30 * min(6, len(self.preview.sheets)) + 8)
        self._checks: list[QCheckBox] = []
        self._edits: list[QLineEdit] = []
        self._spaces: list[QComboBox] = []
        space_list = ctx.spaces.list(enabled_only=True)
        for r, s in enumerate(self.preview.sheets):
            ok = s.header_row is not None
            chk = QCheckBox(); chk.setChecked(s.selected); chk.setEnabled(ok)
            chk.toggled.connect(self._reparse)
            self._checks.append(chk)
            holder = QWidget(); hl = QHBoxLayout(holder); hl.setContentsMargins(12, 0, 0, 0); hl.addWidget(chk)
            self.sheets.setCellWidget(r, 0, holder)
            name = s.name + (" (masquée)" if s.hidden else "")
            self.sheets.setItem(r, 1, QTableWidgetItem(name))
            self.sheets.setItem(r, 2, QTableWidgetItem(str(s.data_rows) if ok else f"ignorée : {s.skip_reason}"))
            ed = QLineEdit(s.default_project); ed.setEnabled(ok and "project" not in s.columns)
            ed.setPlaceholderText("Projet de la feuille" if ok and "project" not in s.columns else "(colonne Projet du fichier)")
            ed.editingFinished.connect(self._reparse)
            self._edits.append(ed)
            self.sheets.setCellWidget(r, 4, ed)
            cb = QComboBox()
            for sp in space_list:
                cb.addItem(f"{sp.icon} {sp.name}", sp.id)
            cb.setCurrentIndex(max(0, cb.findData(s.space_id)))
            cb.setEnabled(ok)
            cb.currentIndexChanged.connect(self._reparse)
            self._spaces.append(cb)
            self.sheets.setCellWidget(r, 3, cb)
        root.addWidget(self.sheets)

        self.update_opt = QCheckBox("Mettre à jour les tâches déjà présentes (statut, deadline, description, responsable, commentaires). "
                                    "Sinon elles sont ignorées.")
        self.update_opt.toggled.connect(self._reparse)
        root.addWidget(self.update_opt)

        root.addWidget(QLabel("<b>2. Prévisualisation</b>"))
        self.summary = QLabel(); root.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Feuille / ligne", "État", "Intitulé", "Projet", "Statut", "Remarques"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents); h.setSectionResizeMode(2, QHeaderView.Stretch); h.setSectionResizeMode(5, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        btns = QHBoxLayout(); btns.addStretch()
        cancel = QPushButton("Annuler"); cancel.clicked.connect(self.reject)
        self.go = QPushButton("Importer"); self.go.setObjectName("primary"); self.go.clicked.connect(self._import)
        btns.addWidget(cancel); btns.addWidget(self.go)
        root.addLayout(btns)
        self._fill()

    def _reparse(self, *_) -> None:
        for s, chk, ed, cb in zip(self.preview.sheets, self._checks, self._edits, self._spaces):
            s.selected = chk.isChecked() and s.header_row is not None
            s.space_id = cb.currentData() or s.space_id
            if ed.isEnabled():
                s.default_project = ed.text().strip()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.ctx.importer.reparse(self.preview, update_existing=self.update_opt.isChecked())
        except Exception as exc:
            show_error(self, exc)
        finally:
            QApplication.restoreOverrideCursor()
        self._fill()

    def _fill(self) -> None:
        c = self.preview.counts()
        self.summary.setText(
            f"<b>{c['new']}</b> nouvelle(s) · <b>{c['update']}</b> à mettre à jour · <b>{c['duplicate']}</b> doublon(s) ignoré(s) · "
            f"<b style='color:#B91C1C'>{c['invalid']}</b> rejetée(s) · <b style='color:#B45309'>{c['warnings']}</b> avec avertissement")
        rows = self.preview.rows
        show = sorted(rows, key=lambda r: (r.state == "new" and not r.messages, r.row_no))[:3000]  # problèmes d'abord
        self.table.setRowCount(len(show))
        for i, r in enumerate(show):
            d = r.data
            vals = [f"{r.sheet} · l.{r.row_no}", STATE_LABELS[r.state], d.title if d else "", d.project_name if d else "",
                    self.ctx.statuses.get(d.status_id).label if d else "", " ; ".join(r.messages)]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if col == 1:
                    it.setForeground(QBrush(QColor(STATE_COLORS[r.state])))
                elif r.messages and r.state in ("new", "update", "invalid") and col == 5:
                    it.setForeground(QBrush(QColor("#B45309")))
                self.table.setItem(i, col, it)
        self.go.setEnabled(c["new"] + c["update"] > 0)
        self.go.setText(f"Importer {c['new'] + c['update']} ligne(s)")

    def _import(self) -> None:
        try:
            self.report = self.ctx.importer.commit(self.preview)
        except ImportFailed as exc:
            QMessageBox.critical(self, "Import annulé", str(exc))
            return
        except Exception as exc:
            show_error(self, exc, "Import impossible")
            return
        self.accept()


class IOPage(Page):
    def __init__(self, ctx, get_view_filter: Callable[[], TaskFilter], parent=None):
        super().__init__(ctx, parent)
        self.get_view_filter = get_view_filter
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        header, _, _ = page_header("Importation et exportation",
                                   "Importez votre historique Excel, exportez vos données, sauvegardez et restaurez la base.")
        root.addWidget(header)

        top = QHBoxLayout()
        imp = Card("Importer un fichier Excel")
        t = QLabel("Fichiers .xlsx ou .xls. Les doublons (même intitulé, même date, même projet) sont détectés ; "
                   "une sauvegarde est faite automatiquement avant l'import.")
        t.setWordWrap(True); imp.lay.addWidget(t)
        b = QPushButton("Choisir un fichier à importer…"); b.setObjectName("primary"); b.clicked.connect(self.import_file)
        imp.lay.addWidget(b)
        self.import_result = QLabel(); self.import_result.setWordWrap(True); imp.lay.addWidget(self.import_result)
        top.addWidget(imp, 1)

        exp = Card("Exporter vers Excel")
        t = QLabel("Le fichier contient la feuille « actions journalières » (même structure que votre fichier actuel) "
                   "et une feuille « Toutes les données ».")
        t.setWordWrap(True); exp.lay.addWidget(t)
        row = QHBoxLayout()
        b1 = QPushButton("Exporter toutes les tâches…"); b1.clicked.connect(lambda: self.export(False))
        b2 = QPushButton("Exporter la vue filtrée…"); b2.clicked.connect(lambda: self.export(True))
        row.addWidget(b1); row.addWidget(b2)
        exp.lay.addLayout(row)
        self.include_trash = QCheckBox("Inclure les tâches de la corbeille")
        exp.lay.addWidget(self.include_trash)
        self.all_spaces = QCheckBox("Inclure tous les espaces (sinon : l'espace affiché)")
        exp.lay.addWidget(self.all_spaces)
        top.addWidget(exp, 1)
        root.addLayout(top)

        bk = Card("Sauvegardes de la base de données")
        self.bk_info = QLabel(); self.bk_info.setObjectName("muted"); self.bk_info.setWordWrap(True)
        bk.lay.addWidget(self.bk_info)
        self.bk_table = QTableWidget(0, 4)
        self.bk_table.setHorizontalHeaderLabels(["Date", "Type", "Taille", "Fichier"])
        self.bk_table.verticalHeader().setVisible(False)
        self.bk_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.bk_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.bk_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.bk_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.bk_table.horizontalHeader().setStretchLastSection(True)
        bk.lay.addWidget(self.bk_table, 1)
        row = QHBoxLayout()
        for label, fn in (("Sauvegarder maintenant", self.backup_now), ("Restaurer la sauvegarde sélectionnée…", self.restore_selected),
                          ("Restaurer depuis un fichier…", self.restore_file), ("Ouvrir le dossier", self.open_folder)):
            x = QPushButton(label); x.clicked.connect(fn); row.addWidget(x)
        row.addStretch()
        bk.lay.addLayout(row)
        root.addWidget(bk, 1)
        self._backups = []

    # -------------------------------------------------------------- import
    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer un fichier Excel", str(Path.home() / "Downloads"),
                                              "Fichiers Excel (*.xlsx *.xlsm *.xls)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dlg = ImportDialog(self.ctx, Path(path), self)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            return show_error(self, exc, "Lecture du fichier impossible")
        QApplication.restoreOverrideCursor()
        if dlg.exec() == QDialog.Accepted and dlg.report:
            r = dlg.report
            msg = (f"Bilan de l'import : {r.imported} importée(s), {r.updated} mise(s) à jour, {r.ignored} ignorée(s) "
                   f"(doublons), {r.rejected} rejetée(s), {r.warnings} avertissement(s).")
            self.import_result.setText(msg + (f"\nSauvegarde préalable : {r.backup.name}" if r.backup else ""))
            QMessageBox.information(self, "Import terminé", msg)
            self.refresh()

    # -------------------------------------------------------------- export
    def export(self, filtered: bool) -> None:
        if filtered:
            tasks = self.ctx.tasks.list(self.get_view_filter(), self.ctx.clock().date())
        else:
            tasks = self.ctx.tasks.all(include_deleted=self.include_trash.isChecked(),
                                       space_id=None if self.all_spaces.isChecked() else CURRENT)
        if not tasks:
            return QMessageBox.information(self, "Export", "Aucune tâche à exporter.")
        stamp = self.ctx.clock().strftime("%Y%m%d_%H%M")
        path, _ = QFileDialog.getSaveFileName(self, "Exporter vers Excel", str(paths.exports_dir() / f"taches_{stamp}.xlsx"),
                                              "Excel (*.xlsx)")
        if not path:
            return
        try:
            n = export_tasks(self.ctx.tasks, tasks, Path(path))
        except PermissionError:
            return QMessageBox.warning(self, "Export impossible",
                                       "Le fichier est ouvert dans Excel ou protégé en écriture. Fermez-le puis réessayez.")
        except Exception as exc:
            return show_error(self, exc, "Export impossible")
        if QMessageBox.question(self, "Export terminé", f"{n} tâche(s) exportée(s).\n\nOuvrir le fichier ?") == QMessageBox.Yes:
            os.startfile(path)  # type: ignore[attr-defined]

    # ---------------------------------------------------------- sauvegardes
    def refresh(self) -> None:
        self._backups = self.ctx.backups.list()
        self.bk_table.setRowCount(len(self._backups))
        for r, b in enumerate(self._backups):
            for c, v in enumerate([fmt_dt(b.created), b.reason_label, f"{b.size / 1024:.0f} Ko", b.path.name]):
                self.bk_table.setItem(r, c, QTableWidgetItem(v))
        self.bk_info.setText(f"Base : {self.ctx.db.path}\nDossier des sauvegardes : {self.ctx.backups.folder}  ·  "
                             f"{len(self._backups)} sauvegarde(s), {self.ctx.settings.get('backup_keep')} conservée(s) au maximum "
                             f"(modifiable dans Paramètres).")

    def backup_now(self) -> None:
        try:
            p = self.ctx.backups.create("manuel")
        except Exception as exc:
            return show_error(self, exc, "Sauvegarde impossible")
        self.refresh()
        QMessageBox.information(self, "Sauvegarde", f"Sauvegarde créée :\n{p}")

    def _restore(self, path: Path) -> None:
        if not confirm(self, "Restaurer une sauvegarde",
                       "La base actuelle sera REMPLACÉE par cette sauvegarde.\nUne sauvegarde de sécurité de l'état actuel "
                       "est créée avant la restauration.", "Restaurer", danger=True):
            return
        try:
            safety = self.ctx.restore_backup(path)
        except Exception as exc:
            return show_error(self, exc, "Restauration impossible")
        self.refresh()
        QMessageBox.information(self, "Restauration terminée", f"Données restaurées.\nÉtat précédent conservé dans : {safety.name}")

    def restore_selected(self) -> None:
        r = self.bk_table.currentRow()
        if 0 <= r < len(self._backups):
            self._restore(self._backups[r].path)
        else:
            QMessageBox.information(self, "Restauration", "Sélectionnez d'abord une sauvegarde dans la liste.")

    def restore_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choisir une sauvegarde", str(self.ctx.backups.folder), "Base de données (*.db)")
        if path:
            self._restore(Path(path))

    def open_folder(self) -> None:
        os.startfile(self.ctx.backups.folder)  # type: ignore[attr-defined]
