"""Journaux techniques (fichier tournant). Aucune donnée sensible n'y est écrite :
les clés API et le contenu des tâches ne sont jamais journalisés."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from . import paths

_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|x-api-key['\"]?\s*[:=]\s*\S+)", re.I)


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET.sub("[clé masquée]", str(record.msg))
        return True


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(getattr(h, "_suivi", False) for h in root.handlers):
        return
    handler = RotatingFileHandler(
        paths.logs_dir() / "suivi.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler._suivi = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(_RedactFilter())
    root.addHandler(handler)
    root.setLevel(level)
