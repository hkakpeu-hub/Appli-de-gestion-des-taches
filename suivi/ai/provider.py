"""Interface commune des fournisseurs d'IA + implémentation Claude (API Messages d'Anthropic).

Aucune dépendance supplémentaire : appel HTTPS direct avec la bibliothèque standard. Un autre
fournisseur peut être ajouté en implémentant ``AIProvider``.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es l'assistant d'analyse d'un outil personnel de suivi de tâches et de projets.
Tu réponds en français, de façon claire et concise. Tu t'appuies UNIQUEMENT sur les données JSON fournies
(« contexte »). Cite les tâches par leur intitulé et leur identifiant (#id), justifie chaque conclusion par
les dates, statuts et priorités observés, et indique explicitement quand une information manque ou quand
l'échantillon est tronqué. N'invente aucune donnée. Tu ne modifies rien : tu analyses et recommandes."""


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


class AIError(Exception):
    """Erreur d'IA lisible par l'utilisateur."""


class AIProvider(ABC):
    @abstractmethod
    def ask(self, history: list[ChatMessage], context_json: str) -> str: ...


class ClaudeProvider(AIProvider):
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, timeout: int = 90):
        if not api_key:
            raise AIError("Aucune clé API configurée.")
        self._key, self.model, self.timeout = api_key, model, timeout

    def ask(self, history: list[ChatMessage], context_json: str) -> str:
        system = f"{SYSTEM_PROMPT}\n\n<contexte>\n{context_json}\n</contexte>"
        body = json.dumps({
            "model": self.model, "max_tokens": 2000, "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in history],
        }).encode("utf-8")
        req = urllib.request.Request(self.URL, data=body, method="POST", headers={
            "content-type": "application/json", "x-api-key": self._key, "anthropic-version": "2023-06-01",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                pass
            log.warning("Erreur API IA : HTTP %s", exc.code)
            if exc.code in (401, 403):
                raise AIError("Clé API refusée. Vérifiez-la dans Paramètres > Assistant IA.") from exc
            if exc.code == 429:
                raise AIError("Limite d'utilisation atteinte. Réessayez dans un instant.") from exc
            raise AIError(f"Erreur du service IA (HTTP {exc.code}). {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AIError("Impossible de joindre le service IA (pas de connexion Internet ?). "
                          "Le reste de l'application fonctionne normalement hors ligne.") from exc
        parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
        return "\n".join(p for p in parts if p).strip() or "(réponse vide)"
