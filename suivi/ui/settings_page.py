"""Paramètres : alertes, planning, sauvegardes, statuts, interface, assistant IA."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..ai import secrets
from ..core.models import KINDS
from .common import Page, confirm, page_header, show_error


class SettingsPage(Page):
    settings_saved = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 16)
        header, hrow, _ = page_header("Paramètres", "Les modifications s'appliquent après « Enregistrer les paramètres ».")
        save = QPushButton("Enregistrer les paramètres"); save.setObjectName("primary"); save.clicked.connect(self.save)
        hrow.addWidget(save)
        outer.addWidget(header)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)
        body = QWidget(); body.setObjectName("content"); scroll.setWidget(body)
        lay = QVBoxLayout(body); lay.setContentsMargins(0, 0, 8, 0); lay.setSpacing(14)
        self.w: dict[str, QWidget] = {}

        def spin(key, lo, hi, suffix=""):
            s = QSpinBox(); s.setRange(lo, hi); s.setSuffix(suffix); self.w[key] = s; return s

        def check(key, label):
            c = QCheckBox(label); self.w[key] = c; return c

        # alertes
        g = QGroupBox("Alertes et notifications"); f = QFormLayout(g)
        f.addRow(check("alerts_enabled", "Activer les alertes"))
        f.addRow(check("native_notifications", "Notifications natives Windows (zone de notification)"))
        rd = QLineEdit(); rd.setPlaceholderText("ex. 7, 3, 1, 0   (0 = le jour de l'échéance)"); self.w["reminder_days"] = rd
        f.addRow("Rappels avant la deadline (jours)", rd)
        f.addRow("Rappel avant l'heure de début", spin("start_reminder_minutes", 1, 600, " min"))
        f.addRow("Avertir avant l'heure de fin", spin("end_warning_minutes", 1, 600, " min"))
        f.addRow("Tâche bloquée au-delà de", spin("blocked_days", 1, 365, " jours"))
        f.addRow("Tâche en attente au-delà de", spin("waiting_days", 1, 365, " jours"))
        f.addRow("Réémettre une alerte de retard tous les", spin("overdue_reemit_days", 1, 90, " jour(s)"))
        f.addRow("Réémettre « non démarrée » tous les", spin("notstarted_reemit_days", 1, 90, " jour(s)"))
        f.addRow("Réémettre « bloquée/en attente » tous les", spin("stuck_reemit_days", 1, 90, " jour(s)"))
        f.addRow("Nombre max. de notifications Windows par vérification", spin("max_toasts_per_check", 1, 20))
        f.addRow("Fréquence de vérification", spin("check_interval_seconds", 15, 3600, " s"))
        lay.addWidget(g)

        g = QGroupBox("Tableau de bord et planning"); f = QFormLayout(g)
        f.addRow("« Échéances à venir » : horizon", spin("upcoming_days", 1, 90, " jours"))
        f.addRow("Tâche « sans mise à jour » après", spin("stale_days", 1, 365, " jours"))
        f.addRow("Début de la journée de travail", spin("work_start_hour", 0, 23, " h"))
        f.addRow("Fin de la journée de travail", spin("work_end_hour", 1, 24, " h"))
        f.addRow("Durée minimale d'un créneau libre", spin("min_free_slot_minutes", 5, 480, " min"))
        lay.addWidget(g)

        g = QGroupBox("Sauvegardes automatiques"); f = QFormLayout(g)
        f.addRow(check("backup_auto", "Sauvegarder automatiquement (au démarrage et pendant l'utilisation)"))
        f.addRow("Intervalle minimum entre deux sauvegardes", spin("backup_interval_hours", 1, 720, " h"))
        f.addRow("Nombre de sauvegardes conservées", spin("backup_keep", 1, 200))
        lay.addWidget(g)

        g = QGroupBox("Interface"); f = QFormLayout(g)
        f.addRow(check("minimize_to_tray", "Réduire dans la zone de notification à la fermeture (les alertes restent actives)"))
        ad = QLineEdit(); self.w["assignee_default"] = ad
        f.addRow("Responsable par défaut des nouvelles tâches", ad)
        lay.addWidget(g)

        # statuts
        g = QGroupBox("Statuts"); v = QVBoxLayout(g)
        v.addWidget(QLabel("Libellés et couleurs personnalisables. La « nature » fixe le comportement : par exemple seule la nature "
                           "« Terminée » ou « Annulée » exclut une tâche des retards."))
        self.status_table = QTableWidget(0, 4)
        self.status_table.setHorizontalHeaderLabels(["Libellé", "Nature", "Couleur", "Actif"])
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.status_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.status_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.status_table.setMinimumHeight(220)
        v.addWidget(self.status_table)
        row = QHBoxLayout()
        for label, fn in (("Ajouter…", self.add_status), ("Renommer…", self.rename_status), ("Couleur…", self.color_status),
                          ("Activer / désactiver", self.toggle_status), ("Supprimer…", self.delete_status)):
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); v.addLayout(row)
        lay.addWidget(g)

        # IA
        g = QGroupBox("Assistant IA (facultatif)"); f = QFormLayout(g)
        self.ai_info = QLabel(); self.ai_info.setWordWrap(True); self.ai_info.setObjectName("muted")
        f.addRow(self.ai_info)
        f.addRow(check("ai_enabled", "Activer l'assistant IA (nécessite Internet ; les données envoyées sont celles de vos tâches)"))
        model = QLineEdit(); self.w["ai_model"] = model
        f.addRow("Modèle Claude", model)
        self.key_edit = QLineEdit(); self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("Collez votre clé API puis cliquez sur « Enregistrer la clé »")
        f.addRow("Clé API Anthropic", self.key_edit)
        krow = QHBoxLayout()
        b1 = QPushButton("Enregistrer la clé (coffre Windows)"); b1.clicked.connect(self.save_key)
        b2 = QPushButton("Supprimer la clé"); b2.clicked.connect(self.delete_key)
        krow.addWidget(b1); krow.addWidget(b2); krow.addStretch()
        f.addRow(krow)
        lay.addWidget(g)
        lay.addStretch()

    # -------------------------------------------------------------------- chargement
    def refresh(self) -> None:
        s = self.ctx.settings
        for key, w in self.w.items():
            val = s.get(key)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            elif isinstance(w, QSpinBox):
                w.setValue(int(val))
            elif key == "reminder_days":
                w.setText(", ".join(str(x) for x in val))
            else:
                w.setText(str(val))
        self._fill_statuses()
        self._ai_status()

    def _ai_status(self) -> None:
        has = bool(secrets.get_api_key())
        self.ai_info.setText(
            ("🔑 Une clé API est enregistrée dans le coffre sécurisé de Windows." if has else "Aucune clé API configurée.")
            + " La clé n'est jamais écrite dans la base, les journaux ou le code. "
              "Sans IA, toutes les autres fonctions restent disponibles.")

    def save(self) -> None:
        s = self.ctx.settings
        try:
            days = [int(x) for x in self.w["reminder_days"].text().replace(";", ",").split(",") if x.strip()]
            if any(d < 0 or d > 365 for d in days):
                raise ValueError
        except ValueError:
            return QMessageBox.warning(self, "Paramètres", "Les rappels doivent être des nombres de jours séparés par des virgules (ex. 7, 3, 1, 0).")
        if self.w["work_end_hour"].value() <= self.w["work_start_hour"].value():
            return QMessageBox.warning(self, "Paramètres", "La fin de la journée de travail doit être après son début.")
        try:
            for key, w in self.w.items():
                if key == "reminder_days":
                    s.set(key, sorted(set(days), reverse=True))
                elif isinstance(w, QCheckBox):
                    s.set(key, w.isChecked())
                elif isinstance(w, QSpinBox):
                    s.set(key, w.value())
                else:
                    s.set(key, w.text().strip())
        except Exception as exc:
            return show_error(self, exc)
        self.settings_saved.emit()
        QMessageBox.information(self, "Paramètres", "Paramètres enregistrés.")

    # -------------------------------------------------------------------- statuts
    def _fill_statuses(self) -> None:
        self._statuses = self.ctx.statuses.list(include_inactive=True)
        self.status_table.setRowCount(len(self._statuses))
        for r, st in enumerate(self._statuses):
            vals = [st.label, KINDS[st.kind], st.color, "oui" if st.is_active else "non"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setBackground(QColor(st.color)); it.setForeground(QColor("white"))
                self.status_table.setItem(r, c, it)

    def _cur(self):
        r = self.status_table.currentRow()
        return self._statuses[r] if 0 <= r < len(self._statuses) else None

    def _changed(self) -> None:
        self.ctx.tasks.notify_changed()
        self._fill_statuses()

    def add_status(self) -> None:
        label, ok = QInputDialog.getText(self, "Nouveau statut", "Libellé :")
        if not ok:
            return
        kind_label, ok = QInputDialog.getItem(self, "Nouveau statut", "Nature (comportement) :", list(KINDS.values()), 0, False)
        if not ok:
            return
        kind = next(k for k, v in KINDS.items() if v == kind_label)
        try:
            self.ctx.statuses.add(label, kind)
        except Exception as exc:
            return show_error(self, exc)
        self._changed()

    def rename_status(self) -> None:
        st = self._cur()
        if not st:
            return
        label, ok = QInputDialog.getText(self, "Renommer le statut", "Libellé :", text=st.label)
        if ok:
            try:
                self.ctx.statuses.update(st.id, label, st.color, st.is_active)
            except Exception as exc:
                return show_error(self, exc)
            self._changed()

    def color_status(self) -> None:
        st = self._cur()
        if st:
            c = QColorDialog.getColor(QColor(st.color), self, "Couleur du statut")
            if c.isValid():
                self.ctx.statuses.update(st.id, st.label, c.name(), st.is_active)
                self._changed()

    def toggle_status(self) -> None:
        st = self._cur()
        if st:
            try:
                self.ctx.statuses.update(st.id, st.label, st.color, not st.is_active)
            except Exception as exc:
                return show_error(self, exc)
            self._changed()

    def delete_status(self) -> None:
        st = self._cur()
        if st and confirm(self, "Supprimer le statut", f"Supprimer le statut « {st.label} » ?", "Supprimer", danger=True):
            try:
                self.ctx.statuses.delete(st.id)
            except Exception as exc:
                return show_error(self, exc)
            self._changed()

    # -------------------------------------------------------------------- clé API
    def save_key(self) -> None:
        key = self.key_edit.text().strip()
        if len(key) < 20:
            return QMessageBox.warning(self, "Clé API", "La clé saisie semble incomplète.")
        try:
            secrets.set_api_key(key)
        except Exception as exc:
            return show_error(self, exc, "Enregistrement de la clé impossible")
        self.key_edit.clear()
        self._ai_status()
        self.settings_saved.emit()
        QMessageBox.information(self, "Clé API", "Clé enregistrée dans le coffre sécurisé de Windows.")

    def delete_key(self) -> None:
        if confirm(self, "Clé API", "Supprimer la clé API enregistrée ?", "Supprimer", danger=True):
            secrets.delete_api_key()
            self._ai_status()
            self.settings_saved.emit()
