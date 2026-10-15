"""Actions système : ouvrir un fichier, l'afficher dans l'explorateur Windows."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def open_path(path: Path | str) -> None:
    """Ouvre un fichier/dossier avec l'application associée (Word, Excel, visionneuse photo…)."""
    os.startfile(str(path))  # type: ignore[attr-defined]


def reveal_in_explorer(path: Path | str) -> None:
    """Ouvre l'explorateur Windows avec le fichier sélectionné."""
    p = Path(path)
    if p.exists():
        subprocess.Popen(["explorer", f"/select,{p}"])
    else:  # fichier absent : on ouvre au moins le dossier existant le plus proche
        parent = p.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        subprocess.Popen(["explorer", str(parent)])
