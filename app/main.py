"""FocusBand entry point: python -m app.main

Starts the Qt app with the theme, deletes old sessions if retention is on (DESIGN §11), and
opens the main window, which starts the vision and logic threads (DESIGN §4).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from typing import Any

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.storage import settings as settings_mod
from app.storage.db import Database
from app.ui import theme
from app.ui.main_window import MainWindow

log = logging.getLogger("focusband")


def delete_old_sessions(settings: dict[str, Any]) -> int:
    days = settings["delete_sessions_after_days"]
    if not days:
        return 0
    with Database() as db:
        n = db.delete_sessions_before(datetime.now().astimezone() - timedelta(days=days))
    if n:
        log.info("Deleted %d sessions older than %d days", n, days)
    return n


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("FocusBand")
    app.setQuitOnLastWindowClosed(False)  # keeps running in the tray when the window is closed

    def restyle() -> None:
        app.setStyleSheet(theme.stylesheet(theme.current()))

    restyle()
    QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: restyle())

    settings = settings_mod.load()
    delete_old_sessions(settings)
    window = MainWindow(settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
