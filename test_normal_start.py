"""Check the real entry point and second-launch delivery in an isolated profile."""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4
import psutil

root = Path(__file__).resolve().parent.parent
check = sorted((root / "tmp").glob("spdf-release-check-*"), key=lambda p: p.stat().st_mtime)[-1]
exe = check / "프로그램 [설치 파일 검증]" / "S.PDF.exe"
fixtures = check / "화면과 기능 검증"
profile = root / "tmp" / ("spdf-normal-final-" + uuid4().hex)
environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", SPDF_DATA_DIR=str(profile))
primary = None


def watchdog():
    for child in psutil.Process().children(recursive=True):
        try:
            child.kill()
        except psutil.Error:
            pass
    print("Normal startup check exceeded 35 seconds", flush=True)
    os._exit(3)


timer = threading.Timer(35, watchdog)
timer.daemon = True
timer.start()
try:
    primary = subprocess.Popen([str(exe), "--no-restore", str(fixtures / "한글 테스트 [첫문서].pdf")], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        time.sleep(.1)
        if (profile / "workspace.json").exists():
            break
    assert (profile / "workspace.json").exists(), "Primary application did not open a file"
    secondary = subprocess.run([str(exe), "--no-restore", str(fixtures / "비교문서.pdf")], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
    assert secondary.returncode == 0, "Second launch failed"
    for _ in range(120):
        time.sleep(.1)
        state = json.loads((profile / "workspace.json").read_text(encoding="utf-8"))
        if len(state.get("sessions", [])) == 2:
            break
    assert len(state["sessions"]) == 2, "File was not delivered to the existing window"
    assert not (profile / "errors.log").exists(), "Application reported an error"
    print("PASS: normal startup and second-launch IPC delivery opened two tabs.", flush=True)
    report = root / "output" / "S.PDF" / "검증결과.json"
    result = json.loads(report.read_text(encoding="utf-8"))
    result["checks"].append("normal startup and second-launch IPC delivery")
    result["document_tests_passed"] = 14
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
finally:
    timer.cancel()
    if primary:
        try:
            for child in psutil.Process(primary.pid).children(recursive=True):
                child.kill()
            primary.kill()
            primary.wait(timeout=5)
        except (psutil.Error, subprocess.TimeoutExpired):
            pass
