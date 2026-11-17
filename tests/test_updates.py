"""Exercise real asynchronous HTTP transfers against a local fixture server."""
import hashlib
import json
import os
import sys
import threading
import time
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl, QObject, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from updates import UpdateManager, Release, verified_pending, file_matches, version_tuple, INSTALLER_NAME, launch_pending_update
from version import REPOSITORY, VERSION


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def server():
    content = b"MZ" + bytes(range(256)) * 3000
    manifest = dict(schema=1, app="S.PDF", repository=REPOSITORY, version="999.0.0", size=len(content), sha256=hashlib.sha256(content).hexdigest())
    state = dict(manifest=manifest, content=content, requests=[], slow=False, redirect=False)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"].append(self.path)
            if state["redirect"]:
                self.send_response(302); self.send_header("Location", "http://example.invalid/untrusted.exe"); self.end_headers(); return
            data = json.dumps(state["manifest"]).encode() if self.path.endswith("update.json") else state["content"]
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
            try:
                for index in range(0, len(data), 8192):
                    self.wfile.write(data[index:index+8192]); self.wfile.flush()
                    if state["slow"]: time.sleep(.02)
            except (BrokenPipeError, ConnectionResetError): pass
        def log_message(self, *args): pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
    class Network(QNetworkAccessManager):
        def createRequest(self, operation, request, outgoingData=None):
            local = QNetworkRequest(request)
            local.setUrl(QUrl(f"http://127.0.0.1:{http.server_port}" + request.url().path()))
            return super().createRequest(operation, local, outgoingData)
    state["network"] = Network
    try: yield state
    finally: http.shutdown(); http.server_close(); thread.join(timeout=2)


def settle(app, condition, seconds=4):
    until = time.monotonic() + seconds
    while not condition() and time.monotonic() < until:
        app.processEvents(); time.sleep(.005)
    assert condition(), "Asynchronous update did not complete"


def manager(app, server, tmp_path):
    network = server["network"]()
    update = UpdateManager(profile=tmp_path, network=network)
    update._test_network = network
    update._messages, update._ready, update._failed = [], [], []
    update.message.connect(update._messages.append)
    update.ready.connect(update._ready.append)
    update.failed.connect(update._failed.append)
    return update


def test_download_and_verified_pending(app, server, tmp_path):
    update = manager(app, server, tmp_path); update.check(manual=True)
    settle(app, lambda: bool(update._ready))
    release, installer = verified_pending(tmp_path)
    assert release.version == "999.0.0" and installer.read_bytes() == server["content"]
    assert file_matches(installer, release)
    assert len(server["requests"]) == 2
    update.check(); assert len(server["requests"]) == 2
    installer.write_bytes(b"tampered"); assert verified_pending(tmp_path) is None


@pytest.mark.parametrize("failure", ["hash", "truncated", "oversized"])
def test_reject_bad_download(app, server, tmp_path, failure):
    if failure == "hash": server["manifest"]["sha256"] = "0" * 64
    elif failure == "truncated": server["content"] = server["content"][:-1]
    else: server["content"] += b"extra"
    update = manager(app, server, tmp_path); update.check(manual=True)
    settle(app, lambda: bool(update._failed))
    assert verified_pending(tmp_path) is None and not list(tmp_path.rglob("*.part"))


def test_current_version_does_not_download(app, server, tmp_path):
    server["manifest"]["version"] = VERSION
    update = manager(app, server, tmp_path); update.check(manual=True)
    settle(app, lambda: update.reply is None)
    assert not update._ready and len(server["requests"]) == 1
    assert "최신" in update._messages[-1]


def test_cancel_transfer_preserves_existing_cache(app, server, tmp_path):
    server["slow"] = True
    update = manager(app, server, tmp_path); update.check()
    settle(app, lambda: update.phase == "installer" and update.bytes_received > 0)
    update.stop(); app.processEvents()
    assert update.reply is None and not list(tmp_path.rglob("*.part")) and not update._ready


def test_reject_insecure_redirect(app, server, tmp_path):
    server["redirect"] = True
    update = manager(app, server, tmp_path); update.check(manual=True)
    settle(app, lambda: bool(update._failed))
    assert len(server["requests"]) == 1 and not update._ready


def test_approve_github_https_redirect(app, tmp_path):
    class Reply(QObject):
        redirectAllowed = Signal()
    reply = Reply(); approved = []
    reply.redirectAllowed.connect(lambda: approved.append(True))
    update = UpdateManager(profile=tmp_path); update.reply = reply
    update._redirected(QUrl("https://release-assets.githubusercontent.com/asset"))
    assert approved == [True]
    update.reply = None


@pytest.mark.parametrize("version", ["../2.2.0", "2.0", "2.0.0-rc1", None, "999999.0.0"])
def test_invalid_versions(version):
    with pytest.raises(ValueError): version_tuple(version)


def test_foreign_manifest_and_pending_path_rejected(tmp_path):
    value = dict(schema=1, app="S.PDF", repository="attacker/s-pdf", version="999.0.0", size=2, sha256="0" * 64)
    with pytest.raises(ValueError): Release.parse(value)
    value["repository"] = REPOSITORY; value["path"] = str(tmp_path / INSTALLER_NAME)
    (tmp_path / "updates").mkdir(); (tmp_path / "updates" / "pending.json").write_text(json.dumps(value))
    assert verified_pending(tmp_path) is None


def test_launch_only_verified_and_enabled_update(tmp_path, monkeypatch):
    folder = tmp_path / "updates" / "999.0.0"; folder.mkdir(parents=True)
    path = folder / INSTALLER_NAME; path.write_bytes(b"MZexample")
    value = dict(schema=1, app="S.PDF", repository=REPOSITORY, version="999.0.0", size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), path=str(path))
    (tmp_path / "updates" / "pending.json").write_text(json.dumps(value))
    monkeypatch.setenv("SPDF_DATA_DIR", str(tmp_path)); monkeypatch.delenv("SPDF_DISABLE_UPDATES", raising=False)
    with patch("updates.application_root", return_value=tmp_path), patch("updates.subprocess.Popen") as process:
        assert launch_pending_update(restart=True, files=["C:/문서 [1].pdf"])
        assert "/restart" in process.call_args.args[0] and process.call_args.args[0][-1] == "C:/문서 [1].pdf"
        assert all(process.call_args.kwargs[key] == subprocess.DEVNULL for key in ["stdin","stdout","stderr"])
        (tmp_path / "settings.json").write_text('{"automatic_updates":false}')
        assert not launch_pending_update(); assert process.call_count == 1
        (tmp_path / "settings.json").write_text('{}'); path.write_bytes(b"tampered")
        assert not launch_pending_update(); assert process.call_count == 1
