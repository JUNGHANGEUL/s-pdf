"""Windows desktop entry point. SPDX-License-Identifier: AGPL-3.0-or-later."""
import argparse
import hashlib
import json
import os
import sys
import traceback
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="S.PDF")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--no-restore", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--test-root")
    parser.add_argument("--sample")
    args = parser.parse_args()
    if args.self_test:
        if not args.test_root:
            parser.error("--self-test requires --test-root")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["SPDF_DATA_DIR"] = str(Path(args.test_root).resolve() / "profile")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QTimer, QIODevice
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from core import data_dir, VERSION
    from window import MainWindow
    app = QApplication([sys.argv[0]])
    app.setApplicationName("S.PDF")
    app.setOrganizationName("S.PDF")
    app.setApplicationVersion(VERSION)
    app.setStyle("Fusion")
    # Explicit registration also supports Windows renderers with no system font
    # enumeration (for example, the isolated offscreen verification platform).
    for filename in ("segoeui.ttf", "segoeuib.ttf", "malgun.ttf", "malgunbd.ttf"):
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    default_font = QFont("Segoe UI", 9)
    default_font.setFamilies(["Segoe UI", "Malgun Gothic", "맑은 고딕"])
    app.setFont(default_font)
    if args.self_test:
        from qa import run
        return run(app, Path(args.test_root).resolve(), args.sample)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SPDF.Desktop.2")
    name = "SPDF-" + hashlib.sha256(os.environ.get("USERNAME", "local-user").encode()).hexdigest()[:18]
    client = QLocalSocket()
    client.connectToServer(name)
    if client.waitForConnected(200):
        client.write((json.dumps({"files": args.files}, ensure_ascii=False) + "\n").encode("utf-8"))
        client.waitForBytesWritten(500)
        client.disconnectFromServer()
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        QMessageBox.warning(None, "S.PDF", "이미 실행 중인 S.PDF 창을 확인해주세요.")
        return 1
    from updates import launch_pending_update
    if launch_pending_update(restart=True, files=args.files):
        server.close()
        return 0
    window = MainWindow(args.files, restore=not args.no_restore)
    sockets = []
    def incoming():
        socket = server.nextPendingConnection()
        sockets.append(socket)
        buffer = bytearray()
        def read():
            buffer.extend(bytes(socket.readAll()))
            if b"\n" not in buffer:
                return
            try:
                message = json.loads(bytes(buffer).split(b"\n", 1)[0].decode("utf-8"))
                paths = [p for p in message.get("files", []) if isinstance(p, str) and Path(p).is_file() and p.lower().endswith(".pdf")]
                def deliver():
                    if window._busy:
                        QTimer.singleShot(300, deliver)
                    else:
                        if paths:
                            window.safe(window.open_paths, paths)
                        window.showNormal()
                        window.raise_()
                        window.activateWindow()
                deliver()
            except (ValueError, OSError):
                pass
            socket.disconnectFromServer()
        socket.readyRead.connect(read)
        socket.disconnected.connect(socket.deleteLater)
        if socket.bytesAvailable():
            read()
    server.newConnection.connect(incoming)
    def exception_hook(kind, value, tb):
        with (data_dir() / "errors.log").open("a", encoding="utf-8") as stream:
            stream.write("".join(traceback.format_exception(kind, value, tb)) + "\n")
        QMessageBox.warning(window, "S.PDF", str(value))
    sys.excepthook = exception_hook
    window.show()
    result = app.exec()
    server.close()
    if result == 0 and window.preferences.get("automatic_updates", True):
        launch_pending_update()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
