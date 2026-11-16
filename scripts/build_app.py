"""Build the packaged FocusBand app with PyInstaller (DESIGN §4 Packaging, §13 days 13–14).

Usage: python scripts/build_app.py [--skip-smoke]
Build on each OS for that OS: macOS gives dist/FocusBand.app, Windows dist/FocusBand/FocusBand.exe.
Checks the models first (python scripts/download_models.py), then runs PyInstaller with
packaging/focusband.spec, ad-hoc signs the macOS app (free, no developer account), and runs
the packaged app's --smoke-test, which loads the models without opening the camera.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vision.model_files import MODELS, MODELS_DIR  # noqa: E402

SPEC = ROOT / "packaging" / "focusband.spec"
DIST = ROOT / "dist"


def check_models() -> bool:
    ok = True
    for name, model in MODELS.items():
        p = MODELS_DIR / name
        if not p.is_file():
            print(f"Missing {p}. Run: python scripts/download_models.py")
            ok = False
        elif hashlib.sha256(p.read_bytes()).hexdigest() != model.sha256:
            print(f"{p} doesn't match its SHA-256. Re-run: python scripts/download_models.py --force")
            ok = False
    return ok


def app_paths() -> tuple[Path, Path]:
    """(what to ship, the executable inside it)."""
    if sys.platform == "darwin":
        bundle = DIST / "FocusBand.app"
        return bundle, bundle / "Contents" / "MacOS" / "FocusBand"
    folder = DIST / "FocusBand"
    return folder, folder / ("FocusBand.exe" if sys.platform == "win32" else "FocusBand")


def size_mb(path: Path) -> float:
    # The macOS bundle links Resources and Frameworks to each other; count each file once.
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink()) / 1e6


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-smoke", action="store_true", help="don't run the packaged app's smoke test")
    args = parser.parse_args()

    if not check_models():
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean",
           "--distpath", str(DIST), "--workpath", str(ROOT / "build")]
    print("Building (several minutes; torch is large)…", flush=True)
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        print("PyInstaller failed.")
        return 1

    ship, exe = app_paths()
    if sys.platform == "darwin" and shutil.which("codesign"):
        # Ad-hoc signature: lets macOS remember the camera and notification permissions.
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(ship)], check=False)
    print(f"Built {ship} ({size_mb(ship):.0f} MB)")

    if args.skip_smoke:
        return 0
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([str(exe), "--smoke-test"], env=env, capture_output=True, text=True, timeout=300)
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "(no output)")
    if r.returncode != 0:
        print(r.stderr[-3000:])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
