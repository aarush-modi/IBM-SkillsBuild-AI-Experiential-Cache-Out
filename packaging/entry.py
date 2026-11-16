"""PyInstaller entry point for the packaged FocusBand app (see packaging/focusband.spec)."""

import multiprocessing
import sys

from app.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # torch and friends may spawn helpers in a frozen app
    sys.exit(main())
