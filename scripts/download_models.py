"""Download the MediaPipe and YOLO model files into models/.

Usage: python scripts/download_models.py [--force]

Files that already exist with the right checksum are skipped; a file with the wrong
checksum (for example a corrupt or partial one) is downloaded again. Each download goes
to a temporary name and is renamed only after its size and SHA-256 are verified, so an
interrupted run never leaves a broken model behind.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.vision.model_files import MODELS, MODELS_DIR, ModelFile  # noqa: E402


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 16):
            h.update(chunk)
    return h.hexdigest()


def download(model: ModelFile, dest: Path) -> int:
    """Download model to dest, verifying length and checksum. Returns the size in bytes."""
    tmp = dest.with_name(dest.name + ".part")
    try:
        try:
            with urllib.request.urlopen(model.url, timeout=60) as resp, tmp.open("wb") as out:
                expected = int(resp.headers.get("Content-Length") or 0)
                h = hashlib.sha256()
                size = 0
                while chunk := resp.read(1 << 16):
                    out.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
        except http.client.HTTPException as e:  # e.g. IncompleteRead; not an OSError
            raise OSError(f"download interrupted: {e!r}") from e
        if size == 0:
            raise OSError("server returned an empty file")
        if expected and size != expected:
            raise OSError(f"incomplete download: got {size} of {expected} bytes")
        if h.hexdigest() != model.sha256:
            raise OSError(f"checksum mismatch: got {h.hexdigest()}, expected {model.sha256}")
        tmp.replace(dest)
        return size
    finally:
        tmp.unlink(missing_ok=True)


def ensure(name: str, model: ModelFile, models_dir: Path, force: bool = False) -> str:
    """Make sure one model is present and valid. Returns a one-line status."""
    dest = models_dir / name
    if dest.is_file() and not force:
        if sha256_of(dest) == model.sha256:
            return f"skip  {name} (already present)"
        print(f"bad   {name} has the wrong checksum; downloading again")
    size = download(model, dest)
    return f"got   {name} ({size / 1e6:.1f} MB)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the MediaPipe and YOLO model files.")
    parser.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name, model in MODELS.items():
        try:
            print(ensure(name, model, MODELS_DIR, args.force))
        except OSError as e:
            print(f"FAILED {name}: {e}")
            failed += 1

    if failed:
        print(f"\n{failed} download(s) failed. Check your connection and run again.")
        return 1
    print(f"\nAll models are in {MODELS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
