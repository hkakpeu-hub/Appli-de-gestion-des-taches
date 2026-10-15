"""Point d'entrée de l'application."""
from __future__ import annotations

import logging
import sys

from . import APP_NAME, paths
from .logging_setup import setup_logging

log = logging.getLogger(__name__)


def main() -> int:
    setup_logging()
    from PySide6.QtCore import QLockFile, Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .context import AppContext
    from .ui.main_window import MainWindow, make_icon
    from .ui.theme import STYLESHEET

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # l'appli reste dans la zone de notification
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(make_icon())

    # une seule instance à la fois : évite deux processus écrivant dans la même base
    lock = QLockFile(str(paths.data_dir() / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QMessageBox.information(None, APP_NAME, "L'application est déjà ouverte (regardez la zone de notification près de l'horloge).")
        return 0

    try:
        ctx = AppContext()
    except Exception as exc:  # base illisible, disque plein…
        log.exception("Ouverture de la base impossible")
        QMessageBox.critical(None, APP_NAME, f"Impossible d'ouvrir la base de données :\n{exc}\n\n"
                             f"Fichier : {paths.db_path()}\nVos sauvegardes sont dans : {paths.backups_dir()}")
        return 1
    try:
        ctx.backups.auto_if_due()
    except Exception:
        log.exception("Sauvegarde automatique au démarrage impossible")

    win = MainWindow(ctx)
    win.show()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
