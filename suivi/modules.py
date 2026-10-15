"""Catalogue des modules d'application affichés sur la page d'accueil.

Les *espaces de tâches* (Travail, Personnel, Kingdom…) sont gérés en base (``SpaceService``).
Les autres modules (budget…) se déclarent ici : ``available=False`` = tuile « bientôt disponible ».
Pour brancher un futur module : mettre ``available=True`` et gérer son ouverture dans ``MainWindow.open_module``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    key: str
    label: str
    icon: str
    description: str
    available: bool = False


MODULES = [
    Module("budget", "Budget personnel", "💶", "Revenus, dépenses et épargne", available=False),
]


def enabled_modules(settings) -> list[Module]:
    flags = settings.get("modules") or {}
    return [m for m in MODULES if flags.get(m.key)]
