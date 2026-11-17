"""Verify updater process handoff through the real launcher, with a harmless probe."""
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4
from version import REPOSITORY

source = Path(__file__).resolve().parent
workspace = source.parent
verified = max((workspace / "tmp").glob("spdf-release-check-*"), key=lambda path: path.stat().st_mtime)
fixture = workspace / "tmp" / ("spdf-update-exit-" + uuid4().hex)
app = fixture / "application"
shutil.copytree(verified / "프로그램 [설치 파일 검증]", app)
profile = fixture / "profile"
cache = profile / "updates" / "9.9.9"
cache.mkdir(parents=True)
probe = cache / "S.PDF-Setup.exe"
compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(probe), str(source / "tests" / "UpdateExitProbe.cs")], check=True)
pending = dict(schema=1, app="S.PDF", repository=REPOSITORY, version="9.9.9", size=probe.stat().st_size,
               sha256=hashlib.sha256(probe.read_bytes()).hexdigest(), path=str(probe.resolve()))
(profile / "updates" / "pending.json").write_text(json.dumps(pending), encoding="utf-8")
(app / ".spdf-install").write_text("test fixture")
for name in ("updates.py", "version.py"):
    shutil.copyfile(source / name, app / "_internal" / name)
(app / "_internal" / "main.py").write_text("from updates import launch_pending_update\nassert launch_pending_update(), 'handoff failed'\n", encoding="utf-8")
environment = dict(os.environ, SPDF_DATA_DIR=str(profile), SPDF_APPLY_TEST_ROOT=str(profile), SPDF_APPLY_TEST_APP=str(app / "S.PDF.exe"))
environment.pop("SPDF_DISABLE_UPDATES", None)
result = subprocess.run([str(app / "S.PDF.exe")], env=environment, capture_output=True, timeout=20)
assert result.returncode == 0, result.stderr
deadline = time.monotonic() + 45
while not (profile / "applied.txt").exists() and time.monotonic() < deadline:
    time.sleep(.05)
if not (profile / "applied.txt").exists():
    diagnostic = {file.name:file.read_text(encoding="utf-8-sig", errors="replace") for file in profile.glob("*.txt")}
    raise AssertionError("Updater could not proceed after launcher exit: " + repr(diagnostic))
assert not (profile / "failed.txt").exists()
print("PASS: real launcher exits before the detached updater applies; no inherited pipe deadlock.")
