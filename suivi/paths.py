"""Emplacements des données de l'application.

Les données (base SQLite, sauvegardes, journaux) sont volontairement stockées
hors du dossier du code, dans ``%LOCALAPPDATA%\\SuiviTaches`` :
 - une mise à jour du code ne touche jamais aux données ;
 - on évite la synchronisation OneDrive d'une base SQLite ouverte (risque de corruption).

La variable d'environnement ``SUIVITACHES_HOME`` permet de forcer un autre dossier
(utilisée par les tests).
"""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("SUIVITACHES_HOME")
    if override:
        base = Path(override)
    else:
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(root) / "SuiviTaches"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "taches.db"


def backups_dir() -> Path:
    p = data_dir() / "sauvegardes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = data_dir() / "journaux"
    p.mkdir(parents=True, exist_ok=True)
    return p


def exports_dir() -> Path:
    p = data_dir() / "exports"
    p.mkdir(parents=True, exist_ok=True)
    return p
