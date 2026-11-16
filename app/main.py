"""FocusBand entry point: python -m app.main

Starts the Qt app with the theme, deletes old sessions if retention is on (DESIGN §11), and
opens the main window, which starts the vision and logic threads (DESIGN §4).
"""

from __future__ import annotations

import copy
import logging
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.storage import settings as settings_mod
from app.storage.settings import DEFAULTS
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


SMOKE_TIMEOUT_S = 120


def smoke_test(app: QApplication) -> int:
    """For packaged builds: build the window, load the models, quit. Uses default settings
    in a temporary folder and never opens the camera. Exit 0 if the models loaded."""
    settings = copy.deepcopy(DEFAULTS)
    error = "models did not load in time"
    with tempfile.TemporaryDirectory() as tmp:
        window = MainWindow(settings, settings_path=Path(tmp) / "settings.json")
        window.timer.stop()  # read the threads' messages here, so an error can't open a dialog
        deadline = time.monotonic() + SMOKE_TIMEOUT_S
        while not window.engine.models_ready and time.monotonic() < deadline:
            for st in window.engine.poll().statuses:
                if st.kind == "error":
                    error, deadline = st.detail, 0.0
            app.processEvents()
            time.sleep(0.05)
        ok = window.engine.models_ready and not window.engine.camera_on
        window.quit()
    print("smoke test: " + ("models loaded, camera untouched" if ok else f"FAILED: {error}"))
    return 0 if ok else 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    if "--smoke-test" in sys.argv:
        return smoke_test(app)
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
