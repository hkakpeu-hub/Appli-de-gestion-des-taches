"""Assistant IA : chat sur vos données (facultatif) + analyses rapides locales."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from ..ai import local_insights, secrets
from ..ai.context import build_context
from ..ai.provider import AIError, ChatMessage, ClaudeProvider
from .common import Card, Page, page_header

log = logging.getLogger(__name__)


class _Worker(QObject):
    done = Signal(str, bool)

    def __init__(self, provider, history, context_json):
        super().__init__()
        self.provider, self.history, self.context_json = provider, history, context_json

    def run(self):
        try:
            self.done.emit(self.provider.ask(self.history, self.context_json), True)
        except AIError as exc:
            self.done.emit(str(exc), False)
        except Exception as exc:  # pragma: no cover
            log.exception("Erreur inattendue de l'assistant IA")
            self.done.emit(f"Erreur inattendue : {exc}", False)


class AIPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.history: list[ChatMessage] = []
        self._thread = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        header, _, self.sub = page_header("Assistant IA", "Posez vos questions sur vos tâches en langage naturel.")
        root.addWidget(header)

        self.banner = QLabel(); self.banner.setWordWrap(True)
        self.banner.setStyleSheet("background:#FFF7ED;border:1px solid #FDBA74;border-radius:8px;padding:10px;")
        root.addWidget(self.banner)

        quick = Card("Analyses rapides (calculées localement, sans Internet)")
        row = QHBoxLayout()
        for label, key in local_insights.QUICK_QUESTIONS.items():
            b = QPushButton(label); b.clicked.connect(lambda _=False, k=key, l=label: self._quick(l, k)); row.addWidget(b)
        quick.lay.addLayout(row)
        root.addWidget(quick)

        self.chat = QTextBrowser(); self.chat.setOpenExternalLinks(False)
        root.addWidget(self.chat, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ex. : Pourquoi ai-je autant de tâches en retard ? · Propose-moi un plan de travail pour demain")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Envoyer"); self.send_btn.setObjectName("primary"); self.send_btn.clicked.connect(self._send)
        clear = QPushButton("Effacer"); clear.clicked.connect(self._clear)
        row.addWidget(self.input, 1); row.addWidget(self.send_btn); row.addWidget(clear)
        root.addLayout(row)
        self._html: list[str] = []

    # -------------------------------------------------------------------
    def ai_ready(self) -> bool:
        return bool(self.ctx.settings.get("ai_enabled") and secrets.get_api_key())

    def refresh(self) -> None:
        if self.ai_ready():
            self.banner.setText(f"✅ Assistant connecté (modèle {self.ctx.settings.get('ai_model')}). Vos questions envoient à Claude "
                                "un résumé de vos tâches ; rien n'est modifié par l'assistant.")
            self.banner.setStyleSheet("background:#F0FDF4;border:1px solid #86EFAC;border-radius:8px;padding:10px;")
        else:
            self.banner.setText("L'assistant IA n'est pas activé. Pour l'utiliser : Paramètres > Assistant IA (activer + clé API). "
                                "En attendant, les analyses rapides ci-dessous fonctionnent sans Internet.")
            self.banner.setStyleSheet("background:#FFF7ED;border:1px solid #FDBA74;border-radius:8px;padding:10px;")
        self.input.setEnabled(self.ai_ready())
        self.send_btn.setEnabled(self.ai_ready())

    def _append(self, who: str, text: str, color: str) -> None:
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
        self._html.append(f"<p><b style='color:{color}'>{who}</b><br>{safe}</p>")
        self.chat.setHtml("".join(self._html))
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def _clear(self) -> None:
        self._html.clear(); self.history.clear(); self.chat.clear()

    def _quick(self, label: str, key: str) -> None:
        self._append("Vous", label, "#1D4ED8")
        self._append("Analyse locale", local_insights.answer(self.ctx, key), "#166534")

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text or self._thread is not None or not self.ai_ready():
            return
        self.input.clear()
        self._append("Vous", text, "#1D4ED8")
        self.history.append(ChatMessage("user", text))
        provider = ClaudeProvider(secrets.get_api_key() or "", self.ctx.settings.get("ai_model"))
        ctx_json = build_context(self.ctx)  # construit dans le fil principal (accès base)
        self._thread = QThread()
        self._worker = _Worker(provider, list(self.history), ctx_json)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_answer)
        self.send_btn.setEnabled(False); self.sub.setText("Réflexion en cours…")
        self._thread.start()

    def _on_answer(self, text: str, ok: bool) -> None:
        self._thread.quit(); self._thread.wait(); self._thread = None
        if ok:
            self.history.append(ChatMessage("assistant", text))
            self._append("Assistant", text, "#166534")
        else:
            self.history.pop()
            self._append("Erreur", text, "#B91C1C")
        self.send_btn.setEnabled(self.ai_ready()); self.sub.setText("Posez vos questions sur vos tâches en langage naturel.")
