"""Download the MediaPipe and YOLO model files into models/.

Usage: python scripts/download_models.py [--force]

Files that already exist are skipped unless --force is given. Each file is downloaded
to a temporary name and renamed when complete, so an interrupted run never leaves a
truncated model behind.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.vision.model_files import MODELS_DIR, URLS  # noqa: E402


def download(url: str, dest: Path) -> int:
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as out:
            size = 0
            while chunk := resp.read(1 << 16):
                out.write(chunk)
                size += len(chunk)
        if size == 0:
            raise OSError("server returned an empty file")
        tmp.replace(dest)
        return size
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name, url in URLS.items():
        dest = MODELS_DIR / name
        if dest.is_file() and not args.force:
            print(f"skip  {name} (already present)")
            continue
        print(f"get   {name} ...", end=" ", flush=True)
        try:
            size = download(url, dest)
        except OSError as e:
            print(f"FAILED: {e}")
            failed += 1
        else:
            print(f"{size / 1e6:.1f} MB")

    if failed:
        print(f"\n{failed} download(s) failed. Check your connection and run again.")
        return 1
    print(f"\nAll models are in {MODELS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
