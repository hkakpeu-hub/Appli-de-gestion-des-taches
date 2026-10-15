"""Lanceur (utilisé par start.bat et par PyInstaller)."""
import sys

from suivi.app import main

if __name__ == "__main__":
    sys.exit(main())
