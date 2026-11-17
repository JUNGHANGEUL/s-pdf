"""Integration checks run in an isolated, invisible Qt platform and data folder."""
import json
import traceback
from pathlib import Path
from unittest.mock import patch

import pymupdf as pdf
from PySide6.QtCore import Qt, QPointF, QEventLoop, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QDialog, QMessageBox

from core import Session, data_dir
from window import MainWindow


def settle(app, milliseconds=180):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()
    app.processEvents()


def run(app, root, sample=None):
    root.mkdir(parents=True, exist_ok=True)
    checks = []
    app.setQuitOnLastWindowClosed(False)
    window = None
    def warning(*args, **kwargs):
        raise AssertionError("Unexpected GUI warning: " + str(args[2] if len(args) > 2 else args))
    warnings = patch.object(QMessageBox, "warning", side_effect=warning)
    warnings.start()
    try:
        first, second = root / "한글 테스트 [첫문서].pdf", root / "비교문서.pdf"
        for target, word in ((first, "ORIGINAL"), (second, "REVISED")):
            with pdf.open() as doc:
                for index in range(3):
                    page = doc.new_page(width=595, height=420)
                    page.insert_text((50, 65), f"{word} PAGE {index + 1}", fontsize=20)
                    page.draw_rect((50, 110, 260, 300), color=None, fill=(.8, .88, 1))
                    page.draw_rect((300, 110, 540, 300), color=None, fill=(.87, .96, .9))
                doc.save(target)
        window = MainWindow(restore=False)
        window.resize(1380, 900)
        window.show()
        settle(app)
        window.open_paths([str(first), str(second)])
        settle(app)
        assert len(window.sessions) == 2 and window.tabs.count() == 2
        window.tabs.setCurrentIndex(0)
        window.go_to(1)
        window.set_zoom(1.5)
        window.canvas.verticalScrollBar().setValue(60)
        scroll = window.canvas.verticalScrollBar().value()
        window.tabs.setCurrentIndex(1)
        window.tabs.setCurrentIndex(0)
        settle(app)
        assert window.session.page == 1 and window.session.zoom == 1.5
        assert window.canvas.verticalScrollBar().value() == scroll
        checks.append("multiple tabs and independent page/zoom")
        window.set_zoom("page")
        settle(app)
        window.mode_buttons["capture"].click()
        settle(app)
        start = window.canvas.mapFromScene(QPointF(50, 110))
        end = window.canvas.mapFromScene(QPointF(260, 300))
        QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(window.canvas.viewport(), end, 30)
        QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        settle(app)
        assert window.session.id in window.capture_regions
        window.copy_capture()
        image = app.clipboard().image()
        assert image.width() > 700 and image.height() > 700
        checks.append("mouse region selection and 300dpi clipboard capture")
        window.capture_scope.setCurrentIndex(1)
        assert window.capture_save.isEnabled()
        for mode, filename in (("view", "01_문서보기.png"), ("capture", "02_고화질캡처.png"), ("pages", "03_페이지구성.png"), ("text", "04_텍스트편집.png")):
            window.set_mode(mode)
            settle(app)
            assert window.mode_buttons[mode].isChecked()
            assert window.grab().save(str(root / filename))
        checks.append("all four workspaces render")
        window.set_mode("text")
        window.go_to(0)
        window.point_picked(QPointF(105, 58))
        assert window.selected_span
        window.text_input.setPlainText("CHANGED")
        window.font_family.setCurrentFont(__import__("PySide6.QtGui", fromlist=["QFont"]).QFont("Arial"))
        window.apply_text()
        assert "CHANGED" in window.session.doc[0].get_text()
        assert "ORIGINAL" not in window.session.doc[0].get_text()
        window.undo()
        assert "ORIGINAL" in window.session.doc[0].get_text()
        window.redo()
        assert "CHANGED" in window.session.doc[0].get_text()
        checks.append("text selection, real replacement, undo, redo")
        window.set_mode("pages")
        settle(app)
        window.gallery.clearSelection()
        window.gallery.item(0).setSelected(True)
        gallery = window.gallery
        target = gallery.visualItemRect(gallery.item(2)).center()
        class Drop:
            def source(self): return gallery
            def position(self): return QPointF(target)
            def setDropAction(self, value): pass
            def accept(self): pass
            def ignore(self): raise AssertionError("Internal page drag was rejected")
        gallery.dropEvent(Drop())
        assert "PAGE 2" in window.session.doc[0].get_text()
        window.undo()
        window.gallery.clearSelection()
        window.gallery.item(1).setSelected(True)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            window.delete_pages()
        assert window.session.count == 2
        window.undo()
        assert window.session.count == 3
        window.reorder_pages([2, 0, 1])
        assert "PAGE 3" in window.session.doc[0].get_text()
        checks.append("gallery delete, reorder and undo")
        window.set_mode("view")
        window.choose_annotation("rectangle")
        window.session.annotate("rectangle", (50, 100, 150, 180), (.9, .2, .3))
        window.after_edit()
        window.sidebar_mode.setCurrentIndex(3)
        assert window.notes_list.count() == 1
        window.notes_list.setCurrentRow(0)
        window.delete_note()
        assert not list(window.session.doc[window.session.page].annots() or [])
        window.session.add_bookmark("QA Bookmark")
        window.after_edit()
        assert window.bookmarks.topLevelItemCount() > 0
        checks.append("annotation add/delete and persistent PDF bookmark")
        window.search_input.setText("PAGE")
        window.search()
        assert len(window.search_results) == 2
        window.toggle_compare()
        settle(app)
        assert window.compare_frame.isVisible() and window.compare_canvas.session is not None
        window.grab().save(str(root / "05_나란히비교.png"))
        checks.append("document search and side-by-side comparison")
        window.toggle_compare()
        output = root / "저장 결과.pdf"
        window.session.save(output)
        with pdf.open(output) as saved:
            assert len(saved) == 3 and "PAGE 3" in saved[0].get_text()
            assert saved.get_toc()[0][1] == "QA Bookmark"
        restored = Session.restore(window.session.folder)
        assert restored.count == 3 and "CHANGED" in restored.doc[1].get_text()
        restored.close()
        checks.append("atomic save/reopen and action-log recovery")
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(root / "print.pdf"))
        with patch("window.QPrintDialog.exec", return_value=QDialog.DialogCode.Accepted):
            window.print_document(printer)
        with pdf.open(root / "print.pdf") as printed:
            assert len(printed) == 3
        checks.append("printing through Qt PDF printer")
        scan_path = root / "OCR scan.pdf"
        with pdf.open() as original:
            page = original.new_page(width=600, height=250)
            page.insert_text((40, 80), "SEARCHABLE OCR", fontsize=36)
            from core import font_path
            page.insert_text((40, 160), "평택시 도로 정비계획", fontname="kr", fontfile=str(font_path()), fontsize=27)
            image = page.get_pixmap(dpi=150)
            with pdf.open() as scan:
                scan.new_page(width=600, height=250).insert_image(page.rect, pixmap=image)
                scan.save(scan_path)
        recognized = Session.open(scan_path, root=root / "ocr-work")
        try:
            recognized.ocr([0])
            assert "SEARCHABLE" in recognized.doc[0].get_text()
            assert "평택" in recognized.doc[0].get_text().replace(" ", "")
            recognized.compress(root / "OCR optimized.pdf", 150, 85)
            with pdf.open(root / "OCR optimized.pdf") as result:
                assert result[0].search_for("SEARCHABLE")
        finally:
            recognized.close()
        checks.append("bundled Korean/English OCR and image compression")
        if sample:
            before = Path(sample).stat().st_size
            window.open_paths([sample])
            window.sidebar_mode.setCurrentIndex(0)
            assert window.session.count == 207
            window.go_to(103)
            window.set_mode("capture")
            window.capture_scope.setCurrentIndex(0)
            settle(app, 350)
            start = window.canvas.mapFromScene(QPointF(150, 130))
            end = window.canvas.mapFromScene(QPointF(700, 460))
            QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
            QTest.mouseMove(window.canvas.viewport(), end, 30)
            QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
            assert window.session.id in window.capture_regions
            window.grab().save(str(root / "06_실제문서_캡처화면.png"))
            clip = window.capture_clip()
            _, size = window.session.capture(root / "실제문서_영역캡처_300dpi.png", dpi=300, clip=clip)
            assert size[0] > 2000 and size[1] > 1000
            window.theme("dark")
            settle(app)
            window.grab().save(str(root / "07_다크모드.png"))
            assert Path(sample).stat().st_size == before
            checks.append("207-page 144MB Korean PDF and dark theme")
        assert not (data_dir() / "errors.log").exists(), (data_dir() / "errors.log").read_text(encoding="utf-8") if (data_dir() / "errors.log").exists() else ""
        (root / "result.json").write_text(json.dumps({"ok": True, "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    except Exception:
        (root / "result.json").write_text(json.dumps({"ok": False, "checks": checks, "error": traceback.format_exc()}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
    finally:
        if window:
            for session in window.sessions:
                session.saved_hash = session.state_hash()
            window.close()
            app.processEvents()
        warnings.stop()
