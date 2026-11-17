"""GitHub release updates; downloads never interrupt document editing.

Only HTTPS release assets belonging to the configured repository are used.
The installer size and SHA256 are checked both after download and before use.
SPDX-License-Identifier: AGPL-3.0-or-later
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, QTimer, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from core import atomic_json, atomic_replace, data_dir, read_json
from version import VERSION, REPOSITORY

MANIFEST_URL = f"https://github.com/{REPOSITORY}/releases/latest/download/update.json"
INSTALLER_NAME = "S.PDF-Setup.exe"
MAX_INSTALLER_SIZE = 1024 * 1024 * 1024
REDIRECT_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}", value):
        raise ValueError("업데이트 버전이 올바르지 않습니다.")
    return tuple(map(int, value.split(".")))


@dataclass(frozen=True)
class Release:
    version: str
    size: int
    sha256: str

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or value.get("schema") != 1 or value.get("app") != "S.PDF" or value.get("repository") != REPOSITORY:
            raise ValueError("S.PDF 업데이트 정보를 확인할 수 없습니다.")
        version_tuple(value.get("version"))
        size, digest = value.get("size"), value.get("sha256")
        if type(size) is not int or not 0 < size <= MAX_INSTALLER_SIZE or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("업데이트 파일의 크기 또는 검증 정보가 올바르지 않습니다.")
        return cls(value["version"], size, digest)

    @property
    def url(self):
        return f"https://github.com/{REPOSITORY}/releases/download/v{self.version}/{INSTALLER_NAME}"

    def manifest(self):
        return dict(schema=1, app="S.PDF", repository=REPOSITORY, version=self.version, size=self.size, sha256=self.sha256)


def file_matches(path, release):
    try:
        path = Path(path)
        if path.stat().st_size != release.size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest() == release.sha256
    except OSError:
        return False


def application_root():
    root = Path(__file__).resolve().parent.parent
    return root if (root / ".spdf-install").is_file() and (root / "S.PDF.exe").is_file() else None


def verified_pending(profile=None, current_version=VERSION):
    profile = Path(profile) if profile else data_dir()
    value = read_json(profile / "updates" / "pending.json", {})
    try:
        release = Release.parse(value)
        if version_tuple(release.version) <= version_tuple(current_version):
            return None
        expected = (profile / "updates" / release.version / INSTALLER_NAME).resolve()
        if Path(value.get("path", "")).resolve() != expected or not file_matches(expected, release):
            return None
        return release, expected
    except (ValueError, OSError, TypeError):
        return None


def launch_pending_update(restart=False, files=None):
    if os.environ.get("SPDF_DISABLE_UPDATES") == "1" or application_root() is None:
        return False
    if not read_json(data_dir() / "settings.json", {}).get("automatic_updates", True):
        return False
    pending = verified_pending()
    if not pending:
        return False
    _, installer = pending
    command = [str(installer), "/update", "/wait", str(os.getpid())]
    if restart:
        command.append("/restart")
        for path in files or []:
            command.extend(["/open", str(path)])
    try:
        subprocess.Popen(command, cwd=str(installer.parent), close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except OSError as error:
        (data_dir() / "update-error.txt").write_text(str(error), encoding="utf-8")
        return False


class UpdateManager(QObject):
    message = Signal(str)
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None, profile=None, network=None):
        super().__init__(parent)
        self.profile = Path(profile) if profile else data_dir()
        self.network = network or QNetworkAccessManager(self)
        self.reply = None
        self.file = None
        self.partial = None
        self.release = None
        self.manual = False
        self.stopped = False
        self.bytes_received = 0
        self.payload = bytearray()
        self.digest = None
        self.network_error = None
        self.phase = None

    def check(self, manual=False):
        if self.reply:
            self.message.emit("업데이트를 확인하고 있습니다…")
            return
        self.manual = manual
        self.stopped = False
        self.message.emit("새 버전을 확인하고 있습니다…")
        pending = verified_pending(self.profile)
        if pending:
            self.release = pending[0]
            self.ready.emit(self.release.version)
            return
        self._request(MANIFEST_URL, "manifest")

    def _request(self, url, phase):
        self.phase = phase
        self.network_error = None
        self.bytes_received = 0
        self.payload = bytearray()
        self.digest = hashlib.sha256()
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", f"S.PDF/{VERSION}".encode("ascii"))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.UserVerifiedRedirectPolicy)
        request.setTransferTimeout(45000 if phase == "installer" else 15000)
        self.reply = self.network.get(request)
        self.reply.redirected.connect(self._redirected)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)

    def _redirected(self, url):
        if url.scheme() == "https" and url.host() in REDIRECT_HOSTS:
            self.reply.redirectAllowed()
        else:
            self.network_error = "업데이트 파일의 다운로드 주소를 확인할 수 없습니다."
            self.reply.abort()

    def _read(self):
        if not self.reply:
            return
        block = bytes(self.reply.readAll())
        self.bytes_received += len(block)
        maximum = self.release.size if self.phase == "installer" else 64 * 1024
        if self.bytes_received > maximum:
            self.network_error = "업데이트 파일이 안내된 크기와 다릅니다."
            self.reply.abort()
            return
        try:
            if self.phase == "installer":
                self.file.write(block)
                self.digest.update(block)
            else:
                self.payload.extend(block)
        except OSError:
            self.network_error = "업데이트 파일을 저장할 공간을 확인해주세요."
            self.reply.abort()

    def _finished(self):
        reply = self.reply
        if not reply:
            return
        self._read()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = self.network_error or (reply.errorString() if reply.error() != QNetworkReply.NetworkError.NoError else None)
        self.reply = None
        reply.deleteLater()
        if self.file:
            self.file.close()
            self.file = None
        if self.stopped:
            self._discard_partial()
            return
        if error or status != 200:
            self._discard_partial()
            # A newly created repository has no release until its first publish.
            if status == 404 and self.phase == "manifest":
                self.message.emit("현재 버전이 최신입니다.")
            else:
                self._fail("업데이트를 확인하지 못했습니다. 인터넷 연결을 확인하고 다시 시도해주세요.")
            return
        try:
            if self.phase == "manifest":
                self.release = Release.parse(json.loads(self.payload.decode("utf-8-sig")))
                if version_tuple(self.release.version) <= version_tuple(VERSION):
                    self.message.emit(f"최신 버전입니다. · S.PDF {VERSION}")
                    return
                folder = self.profile / "updates" / self.release.version
                folder.mkdir(parents=True, exist_ok=True)
                self.partial = folder / (INSTALLER_NAME + ".part")
                self.file = self.partial.open("wb")
                self.message.emit(f"S.PDF {self.release.version} 다운로드 중… 작업을 계속해도 됩니다.")
                self._request(self.release.url, "installer")
            else:
                if self.bytes_received != self.release.size or self.digest.hexdigest() != self.release.sha256:
                    raise ValueError("업데이트 파일 검증에 실패했습니다. 다시 확인해주세요.")
                installer = self.partial.with_name(INSTALLER_NAME)
                atomic_replace(self.partial, installer)
                atomic_json(self.profile / "updates" / "pending.json", dict(self.release.manifest(), path=str(installer.resolve())))
                self.partial = None
                self.ready.emit(self.release.version)
        except (ValueError, OSError, TypeError) as error:
            self._discard_partial()
            self._fail(str(error))

    def _discard_partial(self):
        if self.partial:
            self.partial.unlink(missing_ok=True)
            self.partial = None

    def _fail(self, text):
        self.message.emit(text)
        if self.manual:
            self.failed.emit(text)

    def stop(self):
        self.stopped = True
        if self.reply:
            self.reply.blockSignals(True)
            self.reply.abort()
            self.reply.deleteLater()
            self.reply = None
        if self.file:
            self.file.close()
            self.file = None
        self._discard_partial()
