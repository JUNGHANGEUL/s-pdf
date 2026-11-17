from __future__ import annotations

import contextlib
import json
import math
import os
import shutil
import traceback
from pathlib import Path

import pymupdf as pdf
from PySide6.QtCore import Qt, QSize, QPoint, QRectF, QTimer, QUrl, Signal, QEvent
from PySide6.QtGui import (QAction, QActionGroup, QIcon, QPixmap, QImage, QColor,
    QKeySequence, QShortcut, QDesktopServices, QPainter, QFont, QIntValidator)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QToolButton, QTabBar, QStackedWidget, QSplitter,
    QListWidget, QListWidgetItem, QAbstractItemView, QTreeWidget, QTreeWidgetItem,
    QComboBox, QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QFontComboBox,
    QCheckBox, QColorDialog, QFileDialog, QInputDialog, QMessageBox, QMenu, QToolBar,
    QScrollArea, QProgressDialog, QSizeGrip, QDialog)

from core import Session, PdfError, PasswordRequired, Cancelled, ASSETS, VERSION, data_dir, read_json, atomic_json, parse_pages
from canvas import PdfCanvas, pixmap_image
from dialogs import RangeDialog, MergeDialog, CompressionDialog
from style import stylesheet, icon, BLUE
from updates import UpdateManager, application_root


def qrect(rect):
    return QRectF(rect.x0, rect.y0, rect.width, rect.height)


def prect(rect):
    return pdf.Rect(rect.left(), rect.top(), rect.right(), rect.bottom())


def label(text, name=None):
    result = QLabel(text)
    if name:
        result.setObjectName(name)
    result.setWordWrap(True)
    return result


class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__()
        self.setObjectName("titleBar")
        self.setFixedHeight(43)
        self.window = window
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 4, 0)
        row.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(QIcon(str(ASSETS / "spdf-symbol.svg")).pixmap(26, 26))
        mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(mark)
        word = QLabel('S<span style="color:#3567ed">.</span>PDF')
        word.setObjectName("brand")
        word.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(word)
        self.caption = QLabel("문서 작업을 한곳에서.")
        self.caption.setObjectName("tagline")
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.caption)
        row.addStretch()
        for text, handler, name in (("−", window.showMinimized, "windowMin"), ("□", self.toggle_maximized, "windowMax"), ("×", window.close, "windowClose")):
            button = QToolButton()
            button.setText(text)
            button.setObjectName(name)
            button.setFixedSize(43, 36)
            button.setAccessibleName({"windowMin": "최소화", "windowMax": "최대화 또는 복원", "windowClose": "닫기"}[name])
            button.clicked.connect(handler)
            row.addWidget(button)

    def toggle_maximized(self):
        self.window.showNormal() if self.window.isMaximized() else self.window.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()


class PageGallery(QListWidget):
    orderRequested = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("pageGallery")
        self.setViewMode(self.ViewMode.IconMode)
        self.setResizeMode(self.ResizeMode.Adjust)
        self.setMovement(self.Movement.Snap)
        self.setSpacing(12)
        self.setIconSize(QSize(180, 138))
        self.setGridSize(QSize(204, 174))
        self.setSelectionMode(self.SelectionMode.ExtendedSelection)
        self.setDragDropMode(self.DragDropMode.InternalMove)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        original = [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
        selected = [item.data(Qt.ItemDataRole.UserRole) for item in sorted(self.selectedItems(), key=self.row)]
        if not selected:
            event.ignore()
            return
        target = self.indexAt(event.position().toPoint()).row()
        target = self.count() if target < 0 else target
        selected_set = set(selected)
        insertion = sum(1 for page in original[:target] if page not in selected_set)
        remaining = [page for page in original if page not in selected_set]
        order = remaining[:insertion] + selected + remaining[insertion:]
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        if order != original:
            self.orderRequested.emit(order)


class MainWindow(QMainWindow):
    def __init__(self, initial_files=None, restore=True):
        super().__init__()
        self.setWindowTitle("S.PDF")
        self.setWindowIcon(QIcon(str(ASSETS / "spdf.ico")))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAcceptDrops(True)
        self.setMinimumSize(1040, 650)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1440, screen.width() - 50), min(940, screen.height() - 60))
        self.sessions = []
        self.current_mode = "view"
        self.view_tool = "hand"
        self.capture_regions = {}
        self.selected_span = None
        self.text_rect = None
        self.text_color = QColor("#202c42")
        self.annot_color = QColor("#f0b92f")
        self.search_results = []
        self.thumb_cache = {}
        self._busy = False
        self._switching = False
        self._syncing = False
        self._closing = False
        self.preferences = read_json(data_dir() / "settings.json", {})
        self.recent = self.preferences.get("recent", [])
        self.root = QWidget()
        self.root.setObjectName("appRoot")
        self.setCentralWidget(self.root)
        self.layout = QVBoxLayout(self.root)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.title = TitleBar(self)
        self.layout.addWidget(self.title)
        self.build_tabs()
        self.build_modes()
        self.context = QToolBar()
        self.context.setObjectName("contextBar")
        self.context.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.context.setIconSize(QSize(17, 17))
        self.context.setMovable(False)
        self.context.setStyleSheet("QToolBar{border:0;border-bottom:1px solid #e4e8ef;padding:3px 8px;}")
        self.layout.addWidget(self.context)
        self.build_body()
        self.build_footer()
        self.build_shortcuts()
        self.theme(self.preferences.get("theme", "light"), persist=False)
        QApplication.styleHints().colorSchemeChanged.connect(lambda _: self.theme("system", persist=False) if self.preferences.get("theme") == "system" else None)
        self.build_context()
        self.update_enabled()
        self.thumb_timer = QTimer(self)
        self.thumb_timer.setSingleShot(True)
        self.thumb_timer.setInterval(60)
        self.thumb_timer.timeout.connect(lambda: self.safe(self.render_visible_thumbnails))
        self.thumbnails.verticalScrollBar().valueChanged.connect(lambda: self.thumb_timer.start())
        self.gallery.verticalScrollBar().valueChanged.connect(lambda: self.thumb_timer.start())
        self.autosave = QTimer(self)
        self.autosave.setInterval(2000)
        self.autosave.timeout.connect(self.autosave_tick)
        self.autosave.start()
        QApplication.instance().installEventFilter(self)
        self.initial_files = list(initial_files or [])
        QTimer.singleShot(0, lambda: self.safe(lambda: self.startup(restore)))
        self.updates = UpdateManager(self)
        self.updates.message.connect(self.message)
        self.updates.ready.connect(self.update_ready)
        self.updates.failed.connect(lambda text: QMessageBox.information(self, "S.PDF 업데이트", text))
        if application_root() and self.preferences.get("automatic_updates", True) and os.environ.get("SPDF_DISABLE_UPDATES") != "1":
            QTimer.singleShot(2000, self.updates.check)

    @property
    def session(self):
        index = self.tabs.currentIndex()
        return self.sessions[index] if 0 <= index < len(self.sessions) else None

    def safe(self, function, *args):
        if self._busy or self._closing:
            return None
        try:
            return function(*args)
        except Cancelled as error:
            self.message(str(error))
        except Exception as error:
            log = data_dir() / "errors.log"
            with log.open("a", encoding="utf-8") as stream:
                stream.write(traceback.format_exc() + "\n")
            QMessageBox.warning(self, "S.PDF", str(error) or "작업을 완료하지 못했습니다.")
            if self.session:
                try:
                    self.refresh(False)
                except Exception:
                    pass
        return None

    @contextlib.contextmanager
    def working(self, text, cancellable=False):
        self._busy = True
        self.root.setEnabled(False)
        dialog = QProgressDialog(text, "취소" if cancellable else "", 0, 0, self)
        dialog.setWindowTitle("S.PDF")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        if not cancellable:
            dialog.setCancelButton(None)
        dialog.show()
        QApplication.processEvents()
        try:
            def progress(value, maximum, description):
                dialog.setMaximum(maximum)
                dialog.setValue(value)
                dialog.setLabelText(description)
                QApplication.processEvents()
                return not dialog.wasCanceled()
            yield progress
        finally:
            dialog.close()
            dialog.deleteLater()
            self.root.setEnabled(True)
            self._busy = False

    def button(self, text, function=None, image=None, primary=False):
        result = QPushButton(text)
        if image:
            result.setIcon(icon(image, "#ffffff" if primary else "#68758a"))
        result.setProperty("primary", primary)
        if function:
            result.clicked.connect(lambda checked=False: self.safe(function))
        return result

    def tool(self, text, image, function, checkable=False):
        result = QToolButton()
        result.setText(text)
        result.setIcon(icon(image))
        result.setIconSize(QSize(18, 18))
        result.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        result.setCheckable(checkable)
        result.clicked.connect(lambda checked=False: self.safe(function))
        return result

    def build_tabs(self):
        frame = QFrame()
        frame.setObjectName("tabsFrame")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 7, 12, 0)
        row.setSpacing(3)
        self.tabs = QTabBar()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(lambda _: self.safe(self.switch_tab))
        self.tabs.tabCloseRequested.connect(lambda index: self.safe(self.close_tab, index))
        self.tabs.tabMoved.connect(self.tab_moved)
        row.addWidget(self.tabs, 1)
        add = self.tool("", "plus", self.pick_files)
        add.setToolTip("다른 PDF 열기 (Ctrl+O)")
        add.setAccessibleName("PDF 파일 열기")
        row.addWidget(add)
        self.layout.addWidget(frame)

    def build_modes(self):
        frame = QFrame()
        frame.setObjectName("modeBar")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 7, 12, 7)
        row.setSpacing(5)
        self.open_button = self.tool("열기", "folder-open", self.pick_files)
        row.addWidget(self.open_button)
        self.mode_buttons = {}
        for name, text, image in (("view", "보기", "book-open"), ("capture", "캡처", "scan"), ("pages", "페이지 구성", "layers"), ("text", "텍스트 편집", "type")):
            button = self.tool(text, image, lambda mode=name: self.set_mode(mode), True)
            self.mode_buttons[name] = button
            row.addWidget(button)
        row.addStretch()
        self.undo_button = self.tool("", "undo-2", self.undo)
        self.undo_button.setToolTip("실행 취소 (Ctrl+Z)")
        self.undo_button.setAccessibleName("실행 취소")
        self.redo_button = self.tool("", "redo-2", self.redo)
        self.redo_button.setToolTip("다시 실행 (Ctrl+Y)")
        self.redo_button.setAccessibleName("다시 실행")
        row.addWidget(self.undo_button)
        row.addWidget(self.redo_button)
        self.save_button = self.tool("저장", "save", self.save)
        self.save_button.setToolTip("저장 (Ctrl+S) · 다른 이름으로 저장 (Ctrl+Shift+S)")
        row.addWidget(self.save_button)
        self.menu_button = self.tool("", "settings-2", self.show_menu)
        self.menu_button.setAccessibleName("파일 및 설정 메뉴")
        row.addWidget(self.menu_button)
        self.layout.addWidget(frame)

    def build_body(self):
        self.body_stack = QStackedWidget()
        self.body_stack.setObjectName("welcomeStack")
        self.welcome = QWidget()
        self.welcome.setObjectName("welcome")
        layout = QVBoxLayout(self.welcome)
        layout.addStretch()
        mark = QLabel()
        mark.setPixmap(QIcon(str(ASSETS / "spdf-symbol.svg")).pixmap(80, 80))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(mark)
        name = QLabel("S.PDF")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet("font-size:36px;font-weight:700;margin:14px;")
        layout.addWidget(name)
        hint = label("문서 작업을 한곳에서.\nPDF 파일을 이 창으로 끌어다 놓거나 아래 버튼으로 열어주세요.", "hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.button("PDF 파일 열기", self.pick_files, "folder-open", True))
        row.addStretch()
        layout.addLayout(row)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumSize(650, 180)
        self.recent_list.itemActivated.connect(lambda item: self.safe(self.open_paths, [item.data(Qt.ItemDataRole.UserRole)]))
        recent_row = QHBoxLayout()
        recent_row.addStretch()
        recent_row.addWidget(self.recent_list)
        recent_row.addStretch()
        layout.addLayout(recent_row)
        layout.addStretch()
        self.body_stack.addWidget(self.welcome)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(125)
        self.sidebar.setMaximumWidth(330)
        left = QVBoxLayout(self.sidebar)
        left.setContentsMargins(10, 10, 10, 8)
        left.setSpacing(8)
        self.sidebar_mode = QComboBox()
        self.sidebar_mode.addItems(["페이지", "북마크", "문서 검색", "주석 목록"])
        self.sidebar_mode.currentIndexChanged.connect(self.sidebar_changed)
        left.addWidget(self.sidebar_mode)
        self.sidebar_stack = QStackedWidget()
        self.thumbnails = QListWidget()
        self.thumbnails.setIconSize(QSize(100, 80))
        self.thumbnails.setGridSize(QSize(112, 112))
        self.thumbnails.setSpacing(4)
        self.thumbnails.setFlow(QListWidget.Flow.TopToBottom)
        self.thumbnails.setWrapping(False)
        self.thumbnails.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumbnails.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnails.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnails.setMovement(QListWidget.Movement.Static)
        self.thumbnails.itemClicked.connect(lambda item: self.safe(self.go_to, item.data(Qt.ItemDataRole.UserRole)))
        self.sidebar_stack.addWidget(self.thumbnails)
        bookmarks = QWidget()
        book_layout = QVBoxLayout(bookmarks)
        book_layout.setContentsMargins(0, 0, 0, 0)
        self.bookmarks = QTreeWidget()
        self.bookmarks.setHeaderHidden(True)
        self.bookmarks.itemClicked.connect(lambda item, _: self.safe(self.go_to, item.data(0, Qt.ItemDataRole.UserRole)))
        book_layout.addWidget(self.bookmarks)
        book_layout.addWidget(self.button("현재 페이지 북마크", self.add_bookmark, "bookmark-plus"))
        book_layout.addWidget(self.button("선택 북마크 삭제", self.delete_bookmark, "trash-2"))
        self.sidebar_stack.addWidget(bookmarks)
        search = QWidget()
        search_layout = QVBoxLayout(search)
        search_layout.setContentsMargins(0, 0, 0, 0)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색할 글자")
        self.search_input.returnPressed.connect(lambda: self.safe(self.search))
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.button("문서 검색", self.search, "search"))
        self.search_list = QListWidget()
        self.search_list.itemClicked.connect(lambda item: self.safe(self.search_jump, item))
        search_layout.addWidget(self.search_list)
        self.sidebar_stack.addWidget(search)
        notes = QWidget()
        notes_layout = QVBoxLayout(notes)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        self.notes_list = QListWidget()
        self.notes_list.itemClicked.connect(lambda item: self.safe(self.note_jump, item))
        notes_layout.addWidget(self.notes_list)
        notes_layout.addWidget(self.button("선택 주석 삭제", self.delete_note, "trash-2"))
        self.sidebar_stack.addWidget(notes)
        sources = QWidget()
        sources_layout = QVBoxLayout(sources)
        sources_layout.setContentsMargins(0, 0, 0, 0)
        self.sources_list = QListWidget()
        self.sources_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.sources_list.itemClicked.connect(lambda item: self.tabs.setCurrentIndex(next((i for i, s in enumerate(self.sessions) if s.id == item.data(Qt.ItemDataRole.UserRole)), self.tabs.currentIndex())))
        sources_layout.addWidget(self.sources_list)
        sources_layout.addWidget(self.button("파일 합치기", self.merge_files, "combine"))
        sources_layout.addWidget(label("끌어서 파일 순서를 정한 뒤 합칠 수 있습니다.", "hint"))
        self.sidebar_stack.addWidget(sources)
        self.sidebar_mode.addItem("열린 파일")
        left.addWidget(self.sidebar_stack, 1)
        self.content_splitter.addWidget(self.sidebar)
        self.center_stack = QStackedWidget()
        self.viewer_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = PdfCanvas()
        self.canvas.selectionMade.connect(lambda *args: self.safe(self.selection_made, *args))
        self.canvas.pointPicked.connect(lambda point: self.safe(self.point_picked, point))
        self.canvas.zoomRequested.connect(lambda direction: self.safe(self.change_zoom, direction))
        self.canvas.viewResized.connect(lambda: self.safe(self.refit))
        self.canvas.positionChanged.connect(self.sync_scroll)
        self.viewer_splitter.addWidget(self.canvas)
        self.compare_frame = QFrame()
        compare_layout = QVBoxLayout(self.compare_frame)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("compareHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(8, 4, 8, 4)
        self.compare_combo = QComboBox()
        self.compare_combo.currentIndexChanged.connect(lambda _: self.safe(self.refresh_compare))
        header_row.addWidget(self.compare_combo, 1)
        self.sync_check = QCheckBox("동기화")
        self.sync_check.setChecked(True)
        header_row.addWidget(self.sync_check)
        close_compare = self.tool("", "x", self.toggle_compare)
        header_row.addWidget(close_compare)
        compare_layout.addWidget(header)
        self.compare_canvas = PdfCanvas()
        self.compare_canvas.positionChanged.connect(lambda: self.sync_scroll(True))
        compare_layout.addWidget(self.compare_canvas, 1)
        self.viewer_splitter.addWidget(self.compare_frame)
        self.compare_frame.hide()
        self.center_stack.addWidget(self.viewer_splitter)
        self.gallery = PageGallery()
        self.gallery.orderRequested.connect(lambda order: self.safe(self.reorder_pages, order))
        self.gallery.itemDoubleClicked.connect(lambda item: self.safe(self.gallery_open, item))
        self.gallery.itemSelectionChanged.connect(self.update_page_summary)
        self.center_stack.addWidget(self.gallery)
        self.content_splitter.addWidget(self.center_stack)
        self.inspector_frame = QFrame()
        self.inspector_frame.setObjectName("inspector")
        self.inspector_frame.setMinimumWidth(242)
        self.inspector_frame.setMaximumWidth(320)
        inspector_layout = QVBoxLayout(self.inspector_frame)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        self.inspectors = QStackedWidget()
        inspector_layout.addWidget(self.inspectors)
        self.build_capture_panel()
        self.build_pages_panel()
        self.build_text_panel()
        self.build_annotation_panel()
        self.content_splitter.addWidget(self.inspector_frame)
        self.content_splitter.setSizes([150, 980, 280])
        self.content_splitter.setStretchFactor(1, 1)
        self.body_stack.addWidget(self.content_splitter)
        self.layout.addWidget(self.body_stack, 1)
        self.populate_recent()

    def panel(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget = QWidget()
        widget.setObjectName("inspectorContent")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(19, 19, 19, 17)
        layout.setSpacing(13)
        layout.addWidget(label(title, "sectionTitle"))
        scroll.setWidget(widget)
        self.inspectors.addWidget(scroll)
        return layout

    def build_capture_panel(self):
        layout = self.panel("고화질 캡처")
        layout.addWidget(label("캡처 범위", "hint"))
        self.capture_scope = QComboBox()
        self.capture_scope.addItems(["선택 영역", "현재 페이지 전체"])
        self.capture_scope.currentIndexChanged.connect(lambda _: self.safe(self.capture_scope_changed))
        layout.addWidget(self.capture_scope)
        layout.addWidget(label("해상도", "hint"))
        self.capture_dpi = QComboBox()
        for dpi in (150, 300, 600, 1200):
            self.capture_dpi.addItem(f"{dpi} dpi", dpi)
        self.capture_dpi.setCurrentIndex(1)
        self.capture_dpi.currentIndexChanged.connect(self.update_capture_size)
        layout.addWidget(self.capture_dpi)
        layout.addWidget(label("파일 형식", "hint"))
        self.capture_format = QComboBox()
        self.capture_format.addItem("PNG · 선명한 이미지", "png")
        self.capture_format.addItem("JPG · 작은 용량", "jpg")
        layout.addWidget(self.capture_format)
        self.resolution_label = label("영역을 선택해주세요", "resolution")
        layout.addWidget(self.resolution_label)
        layout.addWidget(label("화면의 확대 배율과 관계없이 PDF를 고해상도로 변환합니다. 원본 이미지의 세밀함에는 영향을 받습니다.", "hint"))
        layout.addStretch()
        self.capture_save = self.button("이미지로 저장", self.save_capture, "download", True)
        self.capture_copy = self.button("클립보드에 복사", self.copy_capture, "clipboard")
        layout.addWidget(self.capture_save)
        layout.addWidget(self.capture_copy)
        layout.addWidget(self.button("여러 페이지 일괄 캡처", self.batch_capture, "images"))

    def build_pages_panel(self):
        layout = self.panel("페이지 구성")
        self.page_summary = label("", "resolution")
        layout.addWidget(self.page_summary)
        layout.addWidget(label("페이지를 끌어서 순서를 바꿉니다. Ctrl·Shift를 누르면 여러 페이지를 선택할 수 있습니다.", "hint"))
        layout.addWidget(self.button("선택 페이지 삭제", self.delete_pages, "trash-2"))
        layout.addWidget(self.button("선택 페이지 추출", self.extract_pages, "files"))
        layout.addWidget(self.button("파일 합치기", self.merge_files, "combine"))
        layout.addWidget(self.button("여러 파일로 분할", self.split_pages, "split"))
        layout.addStretch()
        layout.addWidget(label("다른 이름으로 저장하면 원본을 보관할 수 있습니다. 삭제·이동·회전은 실행 취소할 수 있습니다.", "hint"))
        layout.addWidget(self.button("다른 이름으로 저장", lambda: self.save(True), "save", True))

    def build_text_panel(self):
        layout = self.panel("텍스트 속성")
        self.text_selection_label = label("수정할 글자를 클릭하거나 새 텍스트 영역을 드래그해주세요.", "hint")
        layout.addWidget(self.text_selection_label)
        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText("넣을 글자를 입력하세요")
        self.text_input.setMaximumHeight(110)
        layout.addWidget(self.text_input)
        layout.addWidget(label("글꼴과 크기", "hint"))
        self.font_family = QFontComboBox()
        self.font_family.setCurrentFont(QFont("맑은 고딕"))
        layout.addWidget(self.font_family)
        row = QHBoxLayout()
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(3, 300)
        self.font_size.setValue(12)
        self.font_size.setSuffix(" pt")
        self.font_size.setMinimumHeight(38)
        self.font_size.setStyleSheet("QDoubleSpinBox{padding:3px;} QLineEdit{padding:0;border:0;}")
        row.addWidget(self.font_size)
        self.font_bold = QCheckBox("굵게")
        row.addWidget(self.font_bold)
        layout.addLayout(row)
        self.text_color_button = self.button("글자 색상", self.pick_text_color, "palette")
        layout.addWidget(self.text_color_button)
        self.clear_image = QCheckBox("영역 배경도 지우기 (스캔 글자)")
        layout.addWidget(self.clear_image)
        layout.addWidget(label("원본 글꼴이 없으면 선택한 글꼴로 바뀝니다. 스캔 글자를 고칠 때는 배경도 지울 수 있으며, 주변 그림에 영향이 없는지 확인해주세요.", "hint"))
        layout.addStretch()
        layout.addWidget(self.button("수정 내용 적용", self.apply_text, "check", True))
        layout.addWidget(self.button("선택 취소", self.clear_text_selection))
        layout.addWidget(self.button("한국어·영어 문자 인식", self.run_ocr, "scan-text"))

    def build_annotation_panel(self):
        layout = self.panel("주석 도구")
        layout.addWidget(label("영역을 드래그해서 표시하거나 메모 위치를 클릭해주세요.", "hint"))
        for tool_name, text, image in (("highlight", "형광펜", "highlighter"), ("rectangle", "사각형", "square"), ("arrow", "화살표", "move-up-right"), ("note", "메모", "sticky-note")):
            layout.addWidget(self.button(text, lambda name=tool_name: self.choose_annotation(name), image))
        layout.addWidget(self.button("주석 색상", self.pick_annot_color, "palette"))
        layout.addWidget(self.button("주석 목록 보기", lambda: self.sidebar_mode.setCurrentIndex(3), "list"))
        layout.addStretch()
        layout.addWidget(self.button("이동 도구로 돌아가기", lambda: self.set_view_tool("hand"), "hand"))

    def build_footer(self):
        frame = QFrame()
        frame.setObjectName("footer")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 4, 5, 4)
        self.status = QLabel("PDF 파일을 열어주세요.")
        self.status.setObjectName("statusLabel")
        row.addWidget(self.status, 1)
        self.previous_button = self.tool("", "chevron-left", lambda: self.go_to(self.session.page - 1) if self.session else None)
        self.previous_button.setAccessibleName("이전 페이지")
        row.addWidget(self.previous_button)
        self.page_number = QLineEdit("1")
        self.page_validator = QIntValidator(1, 1, self.page_number)
        self.page_number.setValidator(self.page_validator)
        self.page_number.setFixedWidth(74)
        self.page_number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_number.setAccessibleName("페이지 번호")
        self.page_number.editingFinished.connect(lambda: self.safe(self.go_to, int(self.page_number.text() or "1") - 1))
        row.addWidget(self.page_number)
        self.count_label = QLabel("/ 0")
        row.addWidget(self.count_label)
        self.next_button = self.tool("", "chevron-right", lambda: self.go_to(self.session.page + 1) if self.session else None)
        self.next_button.setAccessibleName("다음 페이지")
        row.addWidget(self.next_button)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setMinimumWidth(125)
        for text, value in (("화면에 맞춤", "page"), ("너비에 맞춤", "width")):
            self.zoom_combo.addItem(text, value)
        for percent in (25, 50, 75, 100, 125, 150, 200, 300, 400, 600):
            self.zoom_combo.addItem(f"{percent}%", percent / 100)
        self.zoom_combo.currentIndexChanged.connect(lambda _: self.safe(self.zoom_selected))
        row.addWidget(self.zoom_combo)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("statusLabel")
        self.zoom_label.setMinimumWidth(40)
        row.addWidget(self.zoom_label)
        row.addSpacing(10)
        row.addWidget(QSizeGrip(self))
        self.layout.addWidget(frame)

    def build_shortcuts(self):
        bindings = {
            "Ctrl+O": self.pick_files, "Ctrl+S": self.save, "Ctrl+Shift+S": lambda: self.save(True),
            "Ctrl+W": lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+Z": self.undo,
            "Ctrl+Y": self.redo, "Ctrl+Shift+Z": self.redo, "Ctrl+F": self.focus_search,
            "Ctrl+P": self.print_document, "Ctrl+R": self.rotate_pages,
            "Ctrl+0": lambda: self.set_zoom("page"), "Ctrl++": lambda: self.change_zoom(1),
            "Ctrl+=": lambda: self.change_zoom(1), "Ctrl+-": lambda: self.change_zoom(-1),
            "Ctrl+Home": lambda: self.go_to(0), "Ctrl+End": lambda: self.go_to(self.session.count - 1) if self.session else None,
            "Ctrl+Tab": lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % len(self.sessions)) if self.sessions else None,
            "Ctrl+Shift+Tab": lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % len(self.sessions)) if self.sessions else None,
        }
        for keys, handler in bindings.items():
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda h=handler: self.safe(h))

    def build_context(self):
        for action in self.context.actions():
            self.context.removeAction(action)
            action.deleteLater()
        def add(text, image, fn, checked=None):
            action = QAction(icon(image), text, self.context)
            if checked is not None:
                action.setCheckable(True)
                action.setChecked(checked)
            action.triggered.connect(lambda _=False: self.safe(fn))
            self.context.addAction(action)
            return action
        if self.current_mode == "view":
            add("이동", "hand", lambda: self.set_view_tool("hand"), self.view_tool == "hand")
            add("글자 선택", "text-select", lambda: self.set_view_tool("select"), self.view_tool == "select")
            add("문서 검색", "search", self.focus_search)
            self.context.addSeparator()
            add("나란히 보기", "columns-2", self.toggle_compare, self.compare_frame.isVisible())
            add("인쇄", "printer", self.print_document)
            self.context.addSeparator()
            menu = QMenu(self)
            for tool_name, text, image in (("highlight", "형광펜", "highlighter"), ("rectangle", "사각형", "square"), ("arrow", "화살표", "move-up-right"), ("note", "메모", "sticky-note")):
                action = menu.addAction(icon(image), text)
                action.triggered.connect(lambda _=False, name=tool_name: self.safe(self.choose_annotation, name))
            button = QToolButton()
            button.setText("주석")
            button.setIcon(icon("message-square"))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.context.addWidget(button)
            add("북마크", "bookmark-plus", self.add_bookmark)
            add("용량 줄이기", "minimize-2", self.compress)
        elif self.current_mode == "capture":
            add("영역 선택", "crop", lambda: self.capture_scope.setCurrentIndex(0))
            add("페이지 전체", "maximize", lambda: self.capture_scope.setCurrentIndex(1))
            self.context.addSeparator()
            add("일괄 캡처", "images", self.batch_capture)
            add("클립보드 복사", "clipboard", self.copy_capture)
        elif self.current_mode == "pages":
            add("파일 추가", "file-plus-2", self.append_files)
            add("파일 합치기", "combine", self.merge_files)
            add("추출", "files", self.extract_pages)
            add("분할", "split", self.split_pages)
            self.context.addSeparator()
            add("왼쪽 회전", "rotate-ccw", lambda: self.rotate_pages(-90))
            add("오른쪽 회전", "rotate-cw", self.rotate_pages)
            add("앞으로 이동", "arrow-left", lambda: self.move_pages(-1))
            add("뒤로 이동", "arrow-right", lambda: self.move_pages(1))
            add("선택 삭제", "trash-2", self.delete_pages)
        else:
            add("기존 글자 수정", "text-cursor-input", lambda: self.text_tool("edit"), self.canvas.tool == "edit")
            add("텍스트 추가", "text-cursor", lambda: self.text_tool("add_text"), self.canvas.tool == "add_text")
            self.context.addSeparator()
            add("문자 인식 · OCR", "scan-text", self.run_ocr)
        self.context.setEnabled(bool(self.session))

    def update_enabled(self):
        session = self.session
        active = bool(session)
        self.body_stack.setCurrentIndex(1 if active else 0)
        for button in self.mode_buttons.values():
            button.setEnabled(active)
        self.mode_buttons[self.current_mode].setChecked(True)
        self.save_button.setEnabled(active)
        self.undo_button.setEnabled(active and session.cursor > 0)
        self.redo_button.setEnabled(active and session.cursor < len(session.actions))
        self.page_number.setEnabled(active)
        self.zoom_combo.setEnabled(active and self.current_mode != "pages")
        self.previous_button.setEnabled(active and session.page > 0)
        self.next_button.setEnabled(active and session.page < session.count - 1)
        self.context.setEnabled(active)
        if not active:
            self.status.setText("PDF 파일을 열어주세요.")
            self.count_label.setText("/ 0")

    def set_mode(self, mode):
        if not self.session:
            return
        self.current_mode = mode
        for name, button in self.mode_buttons.items():
            button.setChecked(name == mode)
        self.center_stack.setCurrentIndex(1 if mode == "pages" else 0)
        self.inspector_frame.setVisible(mode != "view")
        if mode == "capture":
            self.inspectors.setCurrentIndex(0)
            self.capture_scope_changed()
        elif mode == "pages":
            self.inspectors.setCurrentIndex(1)
            self.sidebar_mode.setCurrentIndex(4)
            self.populate_pages()
        elif mode == "text":
            self.inspectors.setCurrentIndex(2)
            self.text_tool("edit")
        else:
            if self.sidebar_mode.currentIndex() == 4:
                self.sidebar_mode.setCurrentIndex(0)
            self.canvas.set_tool(self.view_tool)
            self.canvas.draw_selection(None)
        self.build_context()
        QTimer.singleShot(0, lambda: self.safe(self.refit))

    def switch_tab(self):
        if self._switching:
            return
        previous = self.canvas.session
        if previous and previous in self.sessions:
            previous.scroll = [self.canvas.horizontalScrollBar().value(), self.canvas.verticalScrollBar().value()]
            previous.persist()
        self.selected_span, self.text_rect = None, None
        self.search_results.clear()
        self.search_list.clear()
        self.canvas.selection = None
        self.refresh(True)
        self.restore_scroll_later()
        self.persist_workspace()

    def restore_scroll_later(self):
        active = self.session
        if active:
            saved = list(active.scroll)
            def restore_scroll():
                if self.session is active:
                    self.canvas.horizontalScrollBar().setValue(saved[0])
                    self.canvas.verticalScrollBar().setValue(saved[1])
            QTimer.singleShot(0, restore_scroll)

    def tab_moved(self, old, new):
        if self._switching:
            return
        self.sessions.insert(new, self.sessions.pop(old))
        self.switch_tab()

    def refresh(self, changed=False):
        session = self.session
        self.update_enabled()
        if not session:
            self.canvas.clear_document()
            self.compare_canvas.clear_document()
            self.title.caption.setText("문서 작업을 한곳에서.")
            self.setWindowTitle("S.PDF")
            return
        self.tabs.setTabText(self.tabs.currentIndex(), session.name + (" •" if session.dirty else ""))
        self.tabs.setTabToolTip(self.tabs.currentIndex(), (session.path or session.name) + ("\n저장하지 않은 변경사항" if session.dirty else ""))
        self.setWindowTitle(f"S.PDF — {session.name}")
        self.title.caption.setText(session.name)
        self.page_number.blockSignals(True)
        self.page_validator.setRange(1, session.count)
        self.page_number.setText(str(session.page + 1))
        self.page_number.blockSignals(False)
        self.count_label.setText(f"/ {session.count}")
        self.status.setText("수정됨 · 자동 복구 기록 중" if session.dirty else "내 컴퓨터에서 작업 · 원본 보관")
        if changed:
            self.thumb_cache = {key: value for key, value in self.thumb_cache.items() if key[0] != session.id}
            self.populate_pages()
            self.populate_bookmarks()
            self.populate_notes()
        self.center_stack.setCurrentIndex(1 if self.current_mode == "pages" else 0)
        self.inspector_frame.setVisible(self.current_mode != "view" or self.view_tool in ("highlight", "rectangle", "arrow", "note"))
        self.canvas.load(session, preserve=not changed)
        if self.current_mode == "capture":
            self.capture_scope_changed()
        elif self.current_mode == "text":
            self.inspectors.setCurrentIndex(2)
            self.canvas.set_tool("edit" if self.canvas.tool not in ("edit", "add_text") else self.canvas.tool)
        elif self.current_mode == "view":
            self.canvas.set_tool(self.view_tool)
        self.zoom_label.setText(f"{self.canvas.zoom_percent}%")
        if self.current_mode == "pages":
            self.zoom_label.clear()
        self.zoom_combo.blockSignals(True)
        index = self.zoom_combo.findData(session.zoom)
        if index >= 0:
            self.zoom_combo.setCurrentIndex(index)
        self.zoom_combo.blockSignals(False)
        self.thumbnails.setCurrentRow(session.page)
        self.update_page_summary()
        self.populate_sources()
        self.update_capture_size()
        self.build_context()
        self.refresh_compare_choices()
        self.refresh_compare()
        if hasattr(self, "thumb_timer"):
            self.thumb_timer.start()

    def populate_pages(self):
        session = self.session
        self.thumbnails.clear()
        self.gallery.clear()
        if not session:
            return
        for index in range(session.count):
            for target in (self.thumbnails, self.gallery):
                item = QListWidgetItem(f"{index + 1}")
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setIcon(icon("file-text", "#c0cadd"))
                item.setToolTip(f"{index + 1}페이지")
                if target is self.thumbnails:
                    item.setSizeHint(QSize(108, 108))
                target.addItem(item)
        self.thumbnails.setCurrentRow(session.page)
        if hasattr(self, "thumb_timer"):
            self.thumb_timer.start()

    def render_visible_thumbnails(self):
        session = self.session
        if not session or self._busy:
            return
        targets = [self.gallery] if self.current_mode == "pages" else []
        if self.sidebar_mode.currentIndex() == 0:
            targets.append(self.thumbnails)
        for target in targets:
            bounds = target.viewport().rect().adjusted(0, -180, 0, 180)
            for row in range(target.count()):
                item = target.item(row)
                if not target.visualItemRect(item).intersects(bounds):
                    continue
                page = item.data(Qt.ItemDataRole.UserRole)
                key = (session.id, session.revision, page)
                if key not in self.thumb_cache:
                    rect = session.display_rect(page)
                    dpi = max(12, min(45, int(178 / max(rect.width, rect.height) * 72)))
                    image = session.render(page, dpi=dpi)
                    self.thumb_cache[key] = QIcon(QPixmap.fromImage(pixmap_image(image)))
                    if len(self.thumb_cache) > 180:
                        self.thumb_cache.pop(next(iter(self.thumb_cache)))
                item.setIcon(self.thumb_cache[key])

    def go_to(self, page):
        session = self.session
        if not session or not 0 <= page < session.count or session.page == page:
            return
        session.page = page
        self.selected_span, self.text_rect = None, None
        self.canvas.selection = None
        self.refresh(False)
        self.canvas.verticalScrollBar().setValue(0)
        session.persist()

    def refit(self):
        if self.session and self.current_mode != "pages":
            self.canvas.load(self.session, preserve=True)
            self.zoom_label.setText(f"{self.canvas.zoom_percent}%")
            if self.current_mode == "capture":
                self.capture_scope_changed()
            self.refresh_compare()

    def set_zoom(self, value):
        if self.session:
            self.session.zoom = value
            self.refit()
            self.session.persist()

    def zoom_selected(self):
        self.set_zoom(self.zoom_combo.currentData())

    def change_zoom(self, direction):
        if not self.session:
            return
        current = self.canvas.zoom_percent
        choices = [25, 50, 75, 100, 125, 150, 200, 300, 400, 600]
        values = [v for v in choices if v > current + 1] if direction > 0 else [v for v in reversed(choices) if v < current - 1]
        self.set_zoom((values[0] if values else choices[-1 if direction > 0 else 0]) / 100)

    def set_view_tool(self, tool):
        self.view_tool = tool
        self.current_mode = "view"
        self.set_mode("view")
        self.canvas.set_tool(tool)
        self.inspector_frame.setVisible(tool in ("highlight", "rectangle", "arrow", "note"))
        if self.inspector_frame.isVisible():
            self.inspectors.setCurrentIndex(3)

    def message(self, text):
        self.status.setText(text)

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "PDF 파일 열기", "", "PDF 문서 (*.pdf)")
        if files:
            self.open_paths(files)

    def open_paths(self, paths, activate=True):
        added = []
        for value in paths:
            path = str(Path(value).resolve())
            existing = next((i for i, s in enumerate(self.sessions) if s.path and os.path.normcase(s.path) == os.path.normcase(path)), None)
            if existing is not None:
                if activate:
                    self.tabs.setCurrentIndex(existing)
                added.append(self.sessions[existing])
                continue
            password = ""
            while True:
                try:
                    with self.working(f"{Path(path).name} 여는 중…"):
                        session = Session.open(path, password)
                    break
                except PasswordRequired:
                    password, ok = QInputDialog.getText(self, "PDF 암호", f"{Path(path).name}\n암호를 입력해주세요.", QLineEdit.EchoMode.Password)
                    if not ok:
                        session = None
                        break
            if session:
                self.add_session(session, activate)
                self.recent = [path] + [p for p in self.recent if os.path.normcase(p) != os.path.normcase(path)]
                self.recent = self.recent[:15]
                added.append(session)
        self.populate_recent()
        self.persist_preferences()
        return added

    def add_session(self, session, activate=True):
        previous = self.canvas.session
        if previous and previous in self.sessions:
            previous.scroll = [self.canvas.horizontalScrollBar().value(), self.canvas.verticalScrollBar().value()]
            previous.persist()
        self._switching = True
        self.tabs.blockSignals(True)
        self.sessions.append(session)
        index = self.tabs.addTab(icon("file-text", BLUE), session.name + (" •" if session.dirty else ""))
        close = QToolButton()
        close.setIcon(icon("x"))
        close.setIconSize(QSize(13, 13))
        close.setFixedSize(20, 20)
        close.setStyleSheet("QToolButton{padding:2px;border:0;background:transparent;}")
        close.setToolTip("파일 닫기")
        close.clicked.connect(lambda: self.safe(self.close_tab, self.sessions.index(session)) if session in self.sessions else None)
        self.tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        if activate or len(self.sessions) == 1:
            self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)
        self._switching = False
        self.refresh(True)
        self.restore_scroll_later()
        self.persist_workspace()

    def close_tab(self, index):
        if not 0 <= index < len(self.sessions):
            return True
        session = self.sessions[index]
        if session.dirty:
            answer = QMessageBox.question(self, "변경사항 저장", f"{session.name}\n변경사항을 저장할까요?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Save:
                self.tabs.setCurrentIndex(index)
                if not self.save():
                    return False
        self._switching = True
        self.tabs.blockSignals(True)
        self.tabs.removeTab(index)
        self.sessions.pop(index)
        self.tabs.blockSignals(False)
        self._switching = False
        if self.canvas.session is session:
            self.canvas.clear_document()
        session.close()
        self.capture_regions.pop(session.id, None)
        self.persist_workspace()
        self.refresh(True)
        self.cleanup_session(session)
        return True

    def cleanup_session(self, session):
        root = (data_dir() / "sessions").resolve()
        folder = session.folder.resolve()
        if folder.parent == root and len(folder.name) == 32 and (folder / "session.json").is_file():
            shutil.rmtree(folder, ignore_errors=True)

    def save(self, save_as=False):
        session = self.session
        if not session:
            return False
        destination = session.path
        if save_as or not destination:
            destination, _ = QFileDialog.getSaveFileName(self, "다른 이름으로 저장", session.path or session.name, "PDF 문서 (*.pdf)")
            if not destination:
                return False
            if not destination.lower().endswith(".pdf"):
                destination += ".pdf"
        if session.was_encrypted and not session.password:
            password, ok = QInputDialog.getText(self, "저장 암호", "복구한 암호 문서에 사용할 저장 암호를 입력해주세요.", QLineEdit.EchoMode.Password)
            if not ok or not password:
                return False
            session.password = password
        with self.working("PDF를 저장하고 결과를 확인하는 중…"):
            session.save(destination)
        self.refresh(False)
        self.message(f"저장했습니다 · {Path(destination).name}")
        self.recent = [str(destination)] + [p for p in self.recent if p != str(destination)]
        self.persist_preferences()
        return True

    def undo(self):
        if self.session and self.session.cursor:
            with self.working("작업을 되돌리는 중…"):
                self.session.undo()
            self.after_edit()

    def redo(self):
        if self.session and self.session.cursor < len(self.session.actions):
            with self.working("작업을 다시 적용하는 중…"):
                self.session.redo()
            self.after_edit()

    def after_edit(self):
        self.canvas.selection = None
        self.selected_span, self.text_rect = None, None
        self.search_results.clear()
        self.search_list.clear()
        self.refresh(True)
        self.persist_workspace()

    def selected_pages(self, fallback=True):
        pages = sorted({item.data(Qt.ItemDataRole.UserRole) for item in self.gallery.selectedItems()})
        if not pages and fallback and self.session:
            return [self.session.page]
        return pages

    def update_page_summary(self):
        if self.session:
            selected = len(self.gallery.selectedItems())
            self.page_summary.setText(f"전체 {self.session.count:,}페이지\n{selected}개 선택됨")

    def gallery_open(self, item):
        self.go_to(item.data(Qt.ItemDataRole.UserRole))
        self.set_mode("view")

    def reorder_pages(self, order):
        if self.session:
            current = self.session.page
            self.session.reorder(order)
            self.session.page = order.index(current)
            self.after_edit()

    def move_pages(self, direction):
        if not self.session:
            return
        selected = set(self.selected_pages())
        order = list(range(self.session.count))
        indices = range(len(order)) if direction < 0 else range(len(order) - 1, -1, -1)
        for index in indices:
            neighbor = index + direction
            if order[index] in selected and 0 <= neighbor < len(order) and order[neighbor] not in selected:
                order[index], order[neighbor] = order[neighbor], order[index]
        if order != list(range(self.session.count)):
            self.reorder_pages(order)
            for page in selected:
                self.gallery.item(order.index(page)).setSelected(True)

    def delete_pages(self):
        if not self.session:
            return
        pages = self.selected_pages()
        display = ", ".join(str(p + 1) for p in pages[:20]) + ("…" if len(pages) > 20 else "")
        if QMessageBox.question(self, "페이지 삭제", f"{len(pages)}개 페이지를 작업 문서에서 삭제할까요?\n페이지: {display}\n\n저장 전까지 원본은 그대로이며 Ctrl+Z로 되돌릴 수 있습니다.") != QMessageBox.StandardButton.Yes:
            return
        self.session.delete_pages(pages)
        self.session.page = min(min(pages), self.session.count - 1)
        self.after_edit()

    def rotate_pages(self, angle=90):
        if self.session:
            pages = self.selected_pages() if self.current_mode == "pages" else [self.session.page]
            self.session.rotate(pages, angle)
            self.capture_regions.pop(self.session.id, None)
            self.after_edit()

    def append_files(self):
        if not self.session:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "현재 문서 뒤에 추가할 PDF", "", "PDF 문서 (*.pdf)")
        if files:
            with self.working("페이지를 추가하는 중…"):
                self.session.append(files)
            self.after_edit()

    def merge_files(self):
        order = [self.sources_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sources_list.count())]
        sources = sorted(self.sessions, key=lambda s: order.index(s.id) if s.id in order else len(order))
        dialog = MergeDialog(self, sources)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            with self.working("파일을 새 문서로 합치는 중…"):
                result = Session.merge(dialog.sources())
            self.add_session(result)
            self.set_mode("pages")
            self.message(f"{result.count}페이지를 합쳤습니다. 저장하면 새 PDF가 만들어집니다.")

    def extract_pages(self):
        session = self.session
        if not session:
            return
        default = ",".join(str(p + 1) for p in self.selected_pages())
        dialog = RangeDialog(self, "필요한 페이지 추출", session.count, default)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        pages = parse_pages(dialog.range.text(), session.count)
        destination, _ = QFileDialog.getSaveFileName(self, "추출한 PDF 저장", f"{Path(session.name).stem}_추출.pdf", "PDF 문서 (*.pdf)")
        if destination:
            with self.working("페이지를 추출하는 중…"):
                session.extract(pages, destination)
            self.message(f"{len(pages)}개 페이지를 추출했습니다.")

    def split_pages(self):
        session = self.session
        if not session:
            return
        dialog = RangeDialog(self, "PDF 여러 파일로 분할", session.count, chunk=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        pages = parse_pages(dialog.range.text(), session.count)
        directory = QFileDialog.getExistingDirectory(self, "나눈 PDF를 저장할 폴더")
        if directory:
            with self.working("PDF를 나누는 중…"):
                files = session.split(pages, dialog.chunk.value(), directory)
            self.message(f"{len(files)}개 파일로 나누었습니다. 기존 파일 이름은 덮어쓰지 않았습니다.")

    def capture_scope_changed(self):
        if not self.session:
            return
        if self.capture_scope.currentIndex() == 0:
            self.canvas.set_tool("crop")
            region = self.capture_regions.get(self.session.id)
            self.canvas.draw_selection(qrect(pdf.Rect(region)) if region else None)
        else:
            self.canvas.set_tool("hand")
            self.canvas.draw_selection(None)
        self.update_capture_size()

    def capture_clip(self, required=True):
        if not self.session or self.capture_scope.currentIndex() == 1:
            return None
        region = self.capture_regions.get(self.session.id)
        if not region and required:
            raise PdfError("문서에서 캡처할 영역을 드래그하거나 ‘현재 페이지 전체’를 선택해주세요.")
        return pdf.Rect(region) & self.session.display_rect() if region else None

    def update_capture_size(self):
        if not hasattr(self, "capture_dpi") or not self.session:
            return
        dpi = self.capture_dpi.currentData()
        rect = self.capture_clip(False) if self.capture_scope.currentIndex() == 0 else self.session.display_rect()
        ready = rect is not None and not rect.is_empty
        self.capture_save.setEnabled(ready)
        self.capture_copy.setEnabled(ready)
        if not ready:
            self.resolution_label.setText("문서에서 영역을\n드래그해주세요")
        else:
            pixels = (rect * pdf.Matrix(dpi / 72, dpi / 72)).irect
            w, h = pixels.width, pixels.height
            self.resolution_label.setText(f"{w:,} × {h:,} px\n{dpi} dpi")

    def save_capture(self):
        if not self.session:
            return
        clip = self.capture_clip()
        kind = self.capture_format.currentData()
        name = f"{Path(self.session.name).stem}_{self.session.page + 1:04d}.{kind}"
        target, _ = QFileDialog.getSaveFileName(self, "고화질 이미지 저장", name, "PNG 이미지 (*.png)" if kind == "png" else "JPG 이미지 (*.jpg)")
        if target:
            if not Path(target).suffix:
                target += "." + kind
            with self.working("고해상도 이미지를 만드는 중…"):
                _, size = self.session.capture(target, dpi=self.capture_dpi.currentData(), clip=clip, kind=kind)
            self.message(f"{size[0]:,} × {size[1]:,} px 이미지로 저장했습니다.")

    def copy_capture(self):
        if not self.session:
            return
        clip = self.capture_clip()
        with self.working("클립보드용 이미지를 만드는 중…"):
            data, size = self.session.capture(dpi=self.capture_dpi.currentData(), clip=clip)
            image = QImage.fromData(data, "PNG")
            dots = round(self.capture_dpi.currentData() / .0254)
            image.setDotsPerMeterX(dots)
            image.setDotsPerMeterY(dots)
            QApplication.clipboard().setImage(image)
        self.message(f"클립보드에 복사했습니다 · {size[0]:,} × {size[1]:,} px")

    def batch_capture(self):
        if not self.session:
            return
        clip = self.capture_clip()
        dialog = RangeDialog(self, "여러 페이지 일괄 캡처", self.session.count)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        pages = parse_pages(dialog.range.text(), self.session.count)
        directory = QFileDialog.getExistingDirectory(self, "이미지 저장 폴더")
        if directory:
            normalized = None
            if clip:
                page = self.session.display_rect()
                normalized = (clip.x0 / page.width, clip.y0 / page.height, clip.x1 / page.width, clip.y1 / page.height)
            with self.working("페이지를 캡처하는 중…", True) as progress:
                files = self.session.batch_capture(pages, directory, self.capture_dpi.currentData(), normalized, self.capture_format.currentData(), progress)
            self.message(f"{len(files)}개 페이지를 이미지로 저장했습니다.")

    def selection_made(self, rect, start, end):
        if not self.session:
            return
        if self.current_mode == "capture":
            self.capture_regions[self.session.id] = list(prect(rect))
            self.update_capture_size()
        elif self.current_mode == "text" and self.canvas.tool == "add_text":
            self.text_rect = self.session.to_pdf(prect(rect))
            self.selected_span = None
            self.text_selection_label.setText("새 텍스트 영역을 선택했습니다.")
            self.text_input.setFocus()
        elif self.view_tool == "select":
            text = self.session.selected_text(prect(rect))
            if text:
                QApplication.clipboard().setText(text)
                self.message(f"선택한 글자를 복사했습니다 · {len(text)}자")
            else:
                self.message("선택 영역에 글자가 없습니다. 스캔 문서는 문자 인식을 사용할 수 있습니다.")
        elif self.view_tool in ("highlight", "rectangle", "arrow"):
            self.session.annotate(self.view_tool, prect(rect), self.annot_color.getRgbF()[:3], start=(start.x(), start.y()), end=(end.x(), end.y()))
            self.after_edit()

    def point_picked(self, point):
        if not self.session:
            return
        if self.canvas.tool == "note":
            text, ok = QInputDialog.getMultiLineText(self, "검토 메모", "메모 내용을 입력해주세요.")
            if ok and text.strip():
                self.session.annotate("note", (point.x(), point.y(), point.x() + 16, point.y() + 16), self.annot_color.getRgbF()[:3], text)
                self.after_edit()
            return
        span = self.session.pick_text((point.x(), point.y()))
        if not span:
            self.message("수정할 글자를 찾지 못했습니다. 스캔 문서는 문자 인식을 사용하거나 새 텍스트를 추가해주세요.")
            return
        self.selected_span = span
        self.text_rect = pdf.Rect(span["bbox"])
        self.text_input.setPlainText(span["text"])
        self.font_size.setValue(span["size"])
        self.font_bold.setChecked(bool(span.get("flags", 0) & 16))
        rgb = span.get("color", 0)
        self.text_color = QColor((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255)
        self.text_color_button.setText("글자 색상 · " + self.text_color.name())
        self.text_selection_label.setText("기존 글자를 선택했습니다. 적용 후 모양을 확인해주세요.")
        self.canvas.draw_selection(qrect(self.session.to_display(self.text_rect)))
        self.text_input.setFocus()
        self.text_input.selectAll()

    def text_tool(self, tool):
        self.canvas.set_tool(tool)
        self.clear_text_selection()
        self.build_context()

    def clear_text_selection(self):
        self.selected_span, self.text_rect = None, None
        self.text_input.clear()
        self.canvas.draw_selection(None)
        self.text_selection_label.setText("수정할 글자를 클릭하세요." if self.canvas.tool == "edit" else "문서에서 새 글자를 넣을 영역을 드래그하세요.")

    def pick_text_color(self):
        color = QColorDialog.getColor(self.text_color, self, "글자 색상")
        if color.isValid():
            self.text_color = color
            self.text_color_button.setText("글자 색상 · " + color.name())

    def apply_text(self):
        if not self.session or self.text_rect is None:
            raise PdfError("먼저 수정할 글자를 클릭하거나 새 텍스트 영역을 선택해주세요.")
        span = self.selected_span
        self.session.edit_text(self.text_rect, self.text_input.toPlainText(), self.font_size.value(), self.font_family.currentFont().family(),
                               self.font_bold.isChecked(), color=self.text_color.getRgbF()[:3], replace=span is not None,
                               clear_image=self.clear_image.isChecked(), origin=span.get("origin") if span else None,
                               direction=span.get("direction") if span else None)
        self.after_edit()
        self.text_input.clear()
        self.message("글자를 적용했습니다. 모양을 확인하고 저장해주세요. Ctrl+Z로 되돌릴 수 있습니다.")

    def run_ocr(self):
        if not self.session:
            return
        dialog = RangeDialog(self, "문자 인식 · 기존 글자가 있는 페이지는 건너뜁니다", self.session.count, str(self.session.page + 1), extra=["한국어 + 영어", "한국어", "영어"])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        pages = parse_pages(dialog.range.text(), self.session.count)
        language = ["kor+eng", "kor", "eng"][dialog.extra.currentIndex()]
        with self.working("문자 인식을 준비하는 중…", True) as progress:
            count = self.session.ocr(pages, language, progress=progress)
        self.after_edit()
        self.message(f"{count}개 페이지의 글자를 인식했습니다. 검색·선택 결과를 확인해주세요.")

    def choose_annotation(self, shape):
        self.view_tool = shape
        self.set_view_tool(shape)
        self.annot_color = QColor("#f0bc2f" if shape in ("highlight", "note") else "#df595f")

    def pick_annot_color(self):
        color = QColorDialog.getColor(self.annot_color, self, "주석 색상")
        if color.isValid():
            self.annot_color = color

    def sidebar_changed(self, index):
        self.sidebar_stack.setCurrentIndex(index)
        if index == 1:
            self.populate_bookmarks()
        elif index == 3:
            self.populate_notes()
        elif index == 4:
            self.populate_sources()
        if hasattr(self, "thumb_timer"):
            self.thumb_timer.start()

    def populate_sources(self):
        order = [self.sources_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sources_list.count())]
        sessions = sorted(self.sessions, key=lambda s: order.index(s.id) if s.id in order else len(order))
        self.sources_list.clear()
        for session in sessions:
            item = QListWidgetItem(session.name + f"\n{session.count}페이지" + (" · 수정됨" if session.dirty else ""))
            item.setIcon(icon("grip-vertical"))
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            item.setToolTip(session.path or session.name)
            self.sources_list.addItem(item)
            if session is self.session:
                item.setSelected(True)

    def focus_search(self):
        if self.session:
            self.set_mode("view")
            self.sidebar_mode.setCurrentIndex(2)
            self.search_input.setFocus()
            self.search_input.selectAll()

    def search(self):
        if not self.session:
            return
        with self.working("문서를 검색하는 중…", True) as progress:
            self.search_results = self.session.find(self.search_input.text(), progress)
        self.search_list.clear()
        for index, (page, rect, text) in enumerate(self.search_results):
            item = QListWidgetItem(f"{page + 1}페이지 · {text[:70]}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.search_list.addItem(item)
        self.message(f"검색 결과 {len(self.search_results)}개")
        if self.search_results:
            self.search_jump(self.search_list.item(0))

    def search_jump(self, item):
        page, rect, _ = self.search_results[item.data(Qt.ItemDataRole.UserRole)]
        self.go_to(page)
        self.canvas.show_search([r for p, r, _ in self.search_results if p == page])
        display = self.session.to_display(rect)
        self.canvas.centerOn(display.x0 + display.width / 2, display.y0 + display.height / 2)

    def populate_bookmarks(self):
        self.bookmarks.clear()
        if not self.session:
            return
        parents = {}
        for index, (level, title, page) in enumerate(self.session.doc.get_toc()):
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, page - 1)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, index)
            parent = parents.get(level - 1)
            parent.addChild(item) if parent else self.bookmarks.addTopLevelItem(item)
            parents[level] = item
        self.bookmarks.expandToDepth(1)

    def add_bookmark(self):
        if self.session:
            title, ok = QInputDialog.getText(self, "북마크 추가", "북마크 이름", text=f"{self.session.page + 1}페이지")
            if ok and title.strip():
                self.session.add_bookmark(title.strip())
                self.after_edit()
                self.sidebar_mode.setCurrentIndex(1)

    def delete_bookmark(self):
        item = self.bookmarks.currentItem()
        if not self.session or not item:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole + 1)
        toc = self.session.doc.get_toc()
        end, level = index + 1, toc[index][0]
        while end < len(toc) and toc[end][0] > level:
            end += 1
        self.session.command("북마크 삭제", kind="toc", toc=toc[:index] + toc[end:])
        self.after_edit()

    def populate_notes(self):
        self.notes_list.clear()
        if not self.session:
            return
        for page_index in range(self.session.count):
            page = self.session.doc[page_index]
            for index, annot in enumerate(page.annots() or []):
                text = annot.info.get("content") or annot.type[1]
                item = QListWidgetItem(f"{page_index + 1}페이지 · {text[:80]}")
                item.setToolTip(text)
                item.setData(Qt.ItemDataRole.UserRole, (page_index, index, list(annot.rect)))
                self.notes_list.addItem(item)

    def note_jump(self, item):
        page, _, rect = item.data(Qt.ItemDataRole.UserRole)
        self.go_to(page)
        self.canvas.draw_selection(qrect(self.session.to_display(rect)))

    def delete_note(self):
        item = self.notes_list.currentItem()
        if self.session and item:
            page, index, _ = item.data(Qt.ItemDataRole.UserRole)
            self.session.command("주석 삭제", kind="delete_annot", page=page, index=index)
            self.after_edit()

    def toggle_compare(self):
        if not self.session:
            return
        if self.compare_frame.isVisible():
            self.compare_frame.hide()
            self.build_context()
            QTimer.singleShot(0, lambda: self.safe(self.refit))
            return
        if len(self.sessions) < 2:
            files, _ = QFileDialog.getOpenFileNames(self, "나란히 볼 PDF 선택", "", "PDF 문서 (*.pdf)")
            if files:
                self.open_paths(files, activate=False)
        if len(self.sessions) < 2:
            return
        self.compare_frame.show()
        self.refresh_compare_choices()
        self.viewer_splitter.setSizes([500, 500])
        self.refresh_compare()
        self.build_context()
        QTimer.singleShot(0, lambda: self.safe(self.refit))

    def refresh_compare_choices(self):
        old = self.compare_combo.currentData()
        self.compare_combo.blockSignals(True)
        self.compare_combo.clear()
        for session in self.sessions:
            if session is not self.session:
                self.compare_combo.addItem(session.name, session.id)
        index = self.compare_combo.findData(old)
        self.compare_combo.setCurrentIndex(max(0, index))
        self.compare_combo.blockSignals(False)
        if self.compare_combo.count() == 0:
            self.compare_frame.hide()

    def refresh_compare(self):
        if not self.session or not self.compare_frame.isVisible():
            return
        other = next((s for s in self.sessions if s.id == self.compare_combo.currentData()), None)
        if other:
            self.compare_canvas.load(other, min(self.session.page, other.count - 1), "page", True)

    def sync_scroll(self, from_compare=False):
        if self._syncing or not self.compare_frame.isVisible() or not self.sync_check.isChecked():
            return
        self._syncing = True
        try:
            source, target = (self.compare_canvas, self.canvas) if from_compare else (self.canvas, self.compare_canvas)
            for first, second in ((source.verticalScrollBar(), target.verticalScrollBar()), (source.horizontalScrollBar(), target.horizontalScrollBar())):
                if first.maximum() > 0:
                    second.setValue(round(first.value() / first.maximum() * second.maximum()))
        finally:
            self._syncing = False

    def compress(self):
        session = self.session
        if not session:
            return
        dialog = CompressionDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        target, _ = QFileDialog.getSaveFileName(self, "최적화한 PDF 저장", f"{Path(session.name).stem}_용량줄임.pdf", "PDF 문서 (*.pdf)")
        if not target:
            return
        old_size = Path(session.path).stat().st_size if session.path and Path(session.path).exists() else None
        dpi, quality = dialog.settings()
        with self.working("PDF 용량을 최적화하는 중…"):
            new_size = session.compress(target, dpi, quality)
        if dialog.open_result.isChecked():
            self.open_paths([target])
        message = f"결과 {new_size / 1048576:.2f} MB"
        if old_size:
            message += f" · 기존 파일 {old_size / 1048576:.2f} MB · {(1 - new_size / old_size) * 100:+.1f}% 감소"
        self.message(message)

    def print_document(self, printer=None):
        if not self.session:
            return
        printer = printer or QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        dialog.setMinMax(1, self.session.count)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        begin = max(0, printer.fromPage() - 1) if printer.fromPage() else 0
        end = min(self.session.count, printer.toPage()) if printer.toPage() else self.session.count
        with self.working("인쇄 데이터를 만드는 중…", True) as progress:
            painter = QPainter()
            if not painter.begin(printer):
                raise PdfError("프린터를 시작하지 못했습니다.")
            try:
                for position, index in enumerate(range(begin, end)):
                    if progress(position, end - begin, f"{index + 1}페이지 인쇄") is False:
                        printer.abort()
                        break
                    if position:
                        printer.newPage()
                    image = pixmap_image(self.session.render(index, dpi=min(240, printer.resolution())))
                    bounds = painter.viewport()
                    size = image.size().scaled(bounds.size(), Qt.AspectRatioMode.KeepAspectRatio)
                    target = QRectF((bounds.width() - size.width()) / 2, (bounds.height() - size.height()) / 2, size.width(), size.height())
                    painter.drawImage(target, image)
            finally:
                painter.end()
        self.message("인쇄 데이터를 보냈습니다.")

    def theme(self, value, persist=True):
        dark = value == "dark" or value == "system" and QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        self.setStyleSheet(stylesheet(dark))
        self.context.setStyleSheet(f"QToolBar{{background:{'#191f2a' if dark else '#ffffff'};border:0;border-bottom:1px solid {'#303847' if dark else '#e4e8ef'};padding:3px 8px;}}")
        self.preferences["theme"] = value
        if persist:
            self.persist_preferences()

    def show_menu(self):
        menu = QMenu(self)
        def add(text, function):
            action = menu.addAction(text)
            action.triggered.connect(lambda _=False: self.safe(function))
        add("PDF 파일 열기…   Ctrl+O", self.pick_files)
        add("다른 이름으로 저장…   Ctrl+Shift+S", lambda: self.save(True))
        add("PDF 용량 줄이기…", self.compress)
        add("문자 인식 · OCR…", self.run_ocr)
        menu.addSeparator()
        for text, value in (("밝은 화면", "light"), ("어두운 화면", "dark"), ("Windows 설정에 맞춤", "system")):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(self.preferences.get("theme") == value)
            action.triggered.connect(lambda _=False, v=value: self.theme(v))
        menu.addSeparator()
        action = menu.addAction("다시 실행할 때 마지막 문서 열기")
        action.setCheckable(True)
        action.setChecked(self.preferences.get("restore_tabs", True))
        action.toggled.connect(lambda checked: (self.preferences.update(restore_tabs=checked), self.persist_preferences()))
        menu.addSeparator()
        action = menu.addAction("자동 업데이트 사용")
        action.setCheckable(True)
        action.setChecked(self.preferences.get("automatic_updates", True))
        action.toggled.connect(self.set_automatic_updates)
        add("업데이트 확인…", lambda: self.updates.check(manual=True))
        add("사용 방법 및 프로그램 정보", self.about)
        menu.exec(self.menu_button.mapToGlobal(QPoint(0, self.menu_button.height())))

    def set_automatic_updates(self, checked):
        self.preferences["automatic_updates"] = checked
        self.persist_preferences()
        if not checked:
            self.updates.stop()

    def update_ready(self, version):
        self.message(f"S.PDF {version} 준비 완료 · 문서를 닫고 종료하면 업데이트합니다.")
        if self.updates.manual:
            box = QMessageBox(self)
            box.setWindowTitle("S.PDF 업데이트")
            box.setText(f"S.PDF {version}을 준비했습니다.")
            box.setInformativeText("작업을 마친 뒤 종료하면 새 버전을 적용합니다.\n지금 적용하려면 문서 저장을 확인하고 종료합니다.")
            apply = box.addButton("저장 확인 후 종료", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("계속 작업", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is apply:
                self.preferences["automatic_updates"] = True
                self.close()

    def about(self):
        QMessageBox.information(self, "S.PDF", f"S.PDF {VERSION}\n\n여러 PDF 탭 · 전체/영역/일괄 캡처 · 병합·삭제·추출·분할·회전\n글자 수정·추가 · 주석 · 검색·북마크 · 나란히 비교\n실행 취소·자동 복구 · 용량 줄이기 · 한국어·영어 OCR\n\nCtrl+O 열기 / Ctrl+S 저장 / Ctrl+Shift+S 다른 이름으로 저장\nCtrl+Z 취소 / Ctrl+Y 다시 실행 / Ctrl+F 검색 / Ctrl+P 인쇄\nCtrl+마우스 휠 확대 / Ctrl+0 화면 맞춤 / Ctrl+Tab 탭 전환\n\nPDF는 이 컴퓨터에서만 처리합니다.\n자동 복구를 위해 작업 사본과 변경 기록을 사용자 폴더에 보관합니다.\n글꼴·원본 해상도·스캔 상태에 따라 편집과 OCR 결과가 달라질 수 있습니다.\n\n라이선스: AGPL-3.0-or-later (소스와 제3자 고지는 설치 폴더 참고)")

    def persist_preferences(self):
        self.preferences["recent"] = self.recent[:15]
        atomic_json(data_dir() / "settings.json", self.preferences)

    def populate_recent(self):
        self.recent_list.clear()
        for path in self.recent[:6]:
            if Path(path).exists():
                item = QListWidgetItem(Path(path).name)
                item.setIcon(icon("file-text", BLUE))
                item.setToolTip(path)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.recent_list.addItem(item)
        self.recent_list.setVisible(self.recent_list.count() > 0)

    def persist_workspace(self, clean=False):
        if self._busy or self._closing and not clean:
            return
        if self.session and self.canvas.session is self.session:
            self.session.scroll = [self.canvas.horizontalScrollBar().value(), self.canvas.verticalScrollBar().value()]
        for session in self.sessions:
            session.persist()
        atomic_json(data_dir() / "workspace.json", {"clean": clean, "sessions": [] if clean else [s.id for s in self.sessions],
            "active": self.tabs.currentIndex(), "last_tabs": [{"path": s.path, "page": s.page, "zoom": s.zoom, "scroll": s.scroll} for s in self.sessions if s.path]})

    def autosave_tick(self):
        try:
            self.persist_workspace()
        except OSError:
            self.message("자동 복구 기록을 잠시 저장하지 못했습니다. PDF를 저장해주세요.")

    def startup(self, restore):
        workspace = read_json(data_dir() / "workspace.json", {}) if restore else {}
        recovered = False
        if workspace.get("sessions") and not workspace.get("clean", True):
            choice = QMessageBox.question(self, "자동 복구", "이전에 닫히지 않은 작업이 있습니다. 열린 문서와 변경사항을 복구할까요?")
            if choice == QMessageBox.StandardButton.Yes:
                for session_id in workspace["sessions"]:
                    if isinstance(session_id, str) and len(session_id) == 32 and all(c in "0123456789abcdef" for c in session_id):
                        try:
                            session = Session.restore(data_dir() / "sessions" / session_id)
                            self.add_session(session)
                            recovered = True
                        except Exception as error:
                            QMessageBox.warning(self, "자동 복구", f"일부 작업을 복구하지 못했습니다.\n{error}")
        elif restore and self.preferences.get("restore_tabs", True) and not self.initial_files:
            for item in workspace.get("last_tabs", []):
                if item.get("path") and Path(item["path"]).exists():
                    added = self.open_paths([item["path"]])
                    if added:
                        session = added[0]
                        session.page = min(item.get("page", 0), session.count - 1)
                        session.zoom = item.get("zoom", "page")
                        session.scroll = item.get("scroll", [0, 0])
                        self.refresh(False)
                        self.canvas.horizontalScrollBar().setValue(session.scroll[0])
                        self.canvas.verticalScrollBar().setValue(session.scroll[1])
            if self.session:
                self.refresh(False)
        if self.initial_files:
            self.open_paths(self.initial_files)
        if self.sessions:
            self.tabs.setCurrentIndex(min(max(0, workspace.get("active", 0)), len(self.sessions) - 1))
            self.restore_scroll_later()
        self.persist_workspace()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and not self.isMaximized() and hasattr(event, "globalPosition") and isinstance(watched, QWidget) and watched.window() is self:
            pos = self.mapFromGlobal(event.globalPosition().toPoint())
            edges = Qt.Edge(0)
            if 0 <= pos.x() < 5:
                edges |= Qt.Edge.LeftEdge
            if self.width() - 5 <= pos.x() <= self.width():
                edges |= Qt.Edge.RightEdge
            if 0 <= pos.y() < 5:
                edges |= Qt.Edge.TopEdge
            if self.height() - 5 <= pos.y() <= self.height():
                edges |= Qt.Edge.BottomEdge
            if edges and self.windowHandle():
                self.windowHandle().startSystemResize(edges)
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if self.session and self.canvas.hasFocus():
            if event.key() == Qt.Key.Key_PageDown:
                self.safe(self.go_to, self.session.page + 1)
                return
            if event.key() == Qt.Key.Key_PageUp:
                self.safe(self.go_to, self.session.page - 1)
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.toLocalFile().lower().endswith(".pdf") for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile().lower().endswith(".pdf")]
        if files:
            self.safe(self.open_paths, files)
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
            return
        for index, session in enumerate(self.sessions):
            if session.dirty:
                self.tabs.setCurrentIndex(index)
                answer = QMessageBox.question(self, "변경사항 저장", f"{session.name}\n변경사항을 저장할까요?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
                if answer == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if answer == QMessageBox.StandardButton.Save:
                    try:
                        if not self.save():
                            event.ignore()
                            return
                    except Exception as error:
                        QMessageBox.warning(self, "저장", str(error))
                        event.ignore()
                        return
        self._closing = True
        self.updates.stop()
        self.autosave.stop()
        self.canvas.resize_timer.stop()
        self.compare_canvas.resize_timer.stop()
        self.thumb_timer.stop()
        self.persist_workspace(clean=True)
        self.persist_preferences()
        self.canvas.clear_document()
        self.compare_canvas.clear_document()
        for session in self.sessions:
            session.close()
            self.cleanup_session(session)
        QApplication.instance().removeEventFilter(self)
        event.accept()
