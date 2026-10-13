"""download_models.py and model_files tests, against a local HTTP server (no internet)."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.vision import model_files
from app.vision.model_files import ModelFile
from scripts import download_models as dm

BODY = bytes(range(256)) * 4096  # 1 MiB
SHA = hashlib.sha256(BODY).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        if self.path == "/full":
            self.wfile.write(BODY)
        elif self.path == "/truncated":  # promise 1 MiB, send 300 KB, hang up
            self.wfile.write(BODY[:300_000])
            self.wfile.flush()
            self.close_connection = True
        elif self.path == "/wrong":  # right length, wrong bytes
            self.wfile.write(bytes(len(BODY)))

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def leftovers(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir())


def test_good_download_is_saved(server: str, tmp_path: Path) -> None:
    status = dm.ensure("m.task", ModelFile(f"{server}/full", SHA), tmp_path)
    assert status.startswith("got")
    assert (tmp_path / "m.task").read_bytes() == BODY
    assert leftovers(tmp_path) == ["m.task"]


def test_truncated_download_is_rejected_and_cleaned_up(server: str, tmp_path: Path) -> None:
    with pytest.raises(OSError, match="incomplete|interrupted"):
        dm.ensure("m.task", ModelFile(f"{server}/truncated", SHA), tmp_path)
    assert leftovers(tmp_path) == []  # no model, no .part


def test_checksum_mismatch_is_rejected_and_cleaned_up(server: str, tmp_path: Path) -> None:
    with pytest.raises(OSError, match="checksum"):
        dm.ensure("m.task", ModelFile(f"{server}/wrong", SHA), tmp_path)
    assert leftovers(tmp_path) == []


def test_valid_existing_file_is_skipped(server: str, tmp_path: Path) -> None:
    (tmp_path / "m.task").write_bytes(BODY)
    status = dm.ensure("m.task", ModelFile(f"{server}/wrong", SHA), tmp_path)  # URL would fail if hit
    assert status.startswith("skip")


def test_corrupt_existing_file_is_replaced_without_force(server: str, tmp_path: Path) -> None:
    (tmp_path / "m.task").write_bytes(BODY[:300_000])  # e.g. left by an old, broken run
    status = dm.ensure("m.task", ModelFile(f"{server}/full", SHA), tmp_path)
    assert status.startswith("got")
    assert (tmp_path / "m.task").read_bytes() == BODY


def test_force_redownloads_a_valid_file(server: str, tmp_path: Path) -> None:
    (tmp_path / "m.task").write_bytes(BODY)
    status = dm.ensure("m.task", ModelFile(f"{server}/full", SHA), tmp_path, force=True)
    assert status.startswith("got")


def test_failed_redownload_keeps_nothing_broken(server: str, tmp_path: Path) -> None:
    (tmp_path / "m.task").write_bytes(BODY[:10])
    with pytest.raises(OSError):
        dm.ensure("m.task", ModelFile(f"{server}/truncated", SHA), tmp_path)
    assert not (tmp_path / "m.task.part").exists()


def test_all_models_are_pinned_with_checksums() -> None:
    for name, model in model_files.MODELS.items():
        assert "/latest/" not in model.url, name
        assert len(model.sha256) == 64 and int(model.sha256, 16) >= 0, name


def test_path_raises_with_hint_when_model_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_files, "MODELS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="download_models.py"):
        model_files.path(model_files.POSE)


def test_path_returns_existing_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_files, "MODELS_DIR", tmp_path)
    (tmp_path / model_files.POSE).write_bytes(b"x")
    assert model_files.path(model_files.POSE) == tmp_path / model_files.POSE
