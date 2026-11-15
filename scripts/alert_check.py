"""Developer check: send alerts through the real dispatcher (DESIGN §9), no camera needed.

Usage: python scripts/alert_check.py [--all]
Sends the test alert (rising chirp + notification). With --all, sends one alert of each
pattern a few seconds apart, so the four pings can be told apart by ear. On macOS the first
run asks for notification permission; the pings play either way. Nothing leaves the computer.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alerts.dispatcher import Dispatcher  # noqa: E402
from app.alerts.runner import AlertRunner  # noqa: E402
from app.contracts import (  # noqa: E402
    PATTERN_DISTRACTION, PATTERN_ESCALATED, PATTERN_POSTURE, PATTERN_TEST, Alert,
)
from app.storage import settings as settings_mod  # noqa: E402

GAP_S = 3.0  # between alerts with --all

ALL = [
    Alert("distraction", "phone", PATTERN_DISTRACTION, 0.0),
    Alert("posture", "slouching", PATTERN_POSTURE, 0.0),
    Alert("distraction", "phone", PATTERN_ESCALATED, 0.0),
    Alert("test", "test", PATTERN_TEST, 0.0),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="send one alert of each pattern")
    args = parser.parse_args()

    s = settings_mod.load()
    alerts = ALL if args.all else [ALL[-1]]
    with AlertRunner(Dispatcher.from_settings(s)) as runner:
        try:
            runner.prepare(timeout_s=60)
        except TimeoutError:
            print("No answer to the notification prompt; pings still play.")
        for n, a in enumerate(alerts):
            if n:
                time.sleep(GAP_S)
            alert = Alert(a.kind, a.label, a.pattern, time.time())
            t0 = time.perf_counter()
            sink = runner.submit(alert).result(timeout=10)
            print(f"pattern {alert.pattern} ({alert.kind}: {alert.label}) -> {sink or 'not delivered'}"
                  f" in {(time.perf_counter() - t0) * 1000:.0f} ms")
        time.sleep(1)  # let the last ping finish before exiting
    return 0


if __name__ == "__main__":
    sys.exit(main())
