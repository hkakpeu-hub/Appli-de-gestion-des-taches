"""Stockage sécurisé de la clé API.

La clé est conservée dans le coffre d'identifiants de Windows (Credential Manager) via ``keyring``.
Elle n'est jamais écrite dans la base, les journaux, le code ou le dépôt. À défaut de coffre,
la variable d'environnement ``ANTHROPIC_API_KEY`` est utilisée (lecture seule).
"""
from __future__ import annotations

import os
from typing import Optional

SERVICE = "SuiviTaches"
USER = "anthropic_api_key"


def _keyring():
    try:
        import keyring  # noqa: WPS433
        return keyring
    except Exception:  # pragma: no cover - keyring absent
        return None


def keyring_available() -> bool:
    return _keyring() is not None


def get_api_key() -> Optional[str]:
    kr = _keyring()
    if kr is not None:
        try:
            key = kr.get_password(SERVICE, USER)
            if key:
                return key
        except Exception:
            pass
    return os.environ.get("ANTHROPIC_API_KEY") or None


def set_api_key(key: str) -> None:
    kr = _keyring()
    if kr is None:
        raise RuntimeError("Le coffre sécurisé n'est pas disponible (paquet « keyring » manquant).")
    kr.set_password(SERVICE, USER, key.strip())


def delete_api_key() -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, USER)
        except Exception:
            pass
