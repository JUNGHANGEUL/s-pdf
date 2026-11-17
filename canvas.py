"""PDF canvas in displayed PDF points, with reversible selection overlays."""
from __future__ import annotations
import math
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QPen, QColor, QBrush, QPainter, QPainterPath
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene


def pixmap_image(pix):
    return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()


class PdfCanvas(QGraphicsView):
    selectionMade = Signal(object, object, object)
    pointPicked = Signal(object)
    zoomRequested = Signal(int)
    viewResized = Signal()
    positionChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setObjectName("pdfCanvas")
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(self.Shape.NoFrame)
        self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(self.ViewportAnchor.AnchorViewCenter)
        self.session = None
        self.page_index = 0
        self.tool = "hand"
        self.page_rect = QRectF()
        self.selection = None
        self.overlay = []
        self.search_overlays = []
        self.drag_start = None
        self.drag_end = None
        self._scale = 1.0
        self._middle = None
        self._render_key = None
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(160)
        self.resize_timer.timeout.connect(self.viewResized)
        self.verticalScrollBar().valueChanged.connect(self.positionChanged)
        self.horizontalScrollBar().valueChanged.connect(self.positionChanged)
        self.set_tool("hand")

    def set_tool(self, tool):
        self.tool = tool
        self.setDragMode(self.DragMode.ScrollHandDrag if tool == "hand" else self.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if tool == "hand" else Qt.CursorShape.IBeamCursor if tool == "edit" else Qt.CursorShape.CrossCursor)

    def clear_document(self):
        self.scene().clear()
        self.session = None
        self.overlay, self.search_overlays = [], []
        self.selection = None
        self._render_key = None

    def load(self, session, page_index=None, zoom=None, preserve=False):
        self.session = session
        self.page_index = session.page if page_index is None else page_index
        mode = session.zoom if zoom is None else zoom
        rect = session.display_rect(self.page_index)
        self.page_rect = QRectF(0, 0, rect.width, rect.height)
        available = self.viewport().size()
        if mode == "page":
            scale = min(max(100, available.width() - 64) / rect.width, max(100, available.height() - 64) / rect.height)
        elif mode == "width":
            scale = max(100, available.width() - 64) / rect.width
        else:
            scale = max(.1, min(6.0, float(mode))) * self.logicalDpiX() / 72
        old_scroll = (self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        self.resetTransform()
        self.scale(scale, scale)
        self._scale = scale
        dpi = min(360, max(90, math.ceil(scale * self.devicePixelRatioF() * 72)))
        dpi = min(dpi, max(36, int(math.sqrt(24_000_000 / (rect.width * rect.height)) * 72)))
        key = (session.id, session.revision, self.page_index, dpi)
        if key != self._render_key:
            self.scene().clear()
            self.overlay, self.search_overlays = [], []
            pix = session.render(self.page_index, dpi=dpi, max_pixels=26_000_000)
            shadow = self.scene().addRect(QRectF(3, 4, rect.width, rect.height), QPen(Qt.PenStyle.NoPen), QBrush(QColor(25, 40, 65, 22)))
            shadow.setZValue(-1)
            item = self.scene().addPixmap(QPixmap.fromImage(pixmap_image(pix)))
            item.setScale(72 / dpi)
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.scene().setSceneRect(QRectF(-24, -24, rect.width + 48, rect.height + 48))
            self._render_key = key
        if preserve:
            self.horizontalScrollBar().setValue(old_scroll[0])
            self.verticalScrollBar().setValue(old_scroll[1])
        else:
            self.centerOn(rect.width / 2, rect.height / 2)
            self.verticalScrollBar().setValue(0)
        self.draw_selection(self.selection)

    @property
    def zoom_percent(self):
        return round(self._scale * 72 / self.logicalDpiX() * 100)

    def _remove(self, items):
        for item in items:
            try:
                if item.scene():
                    self.scene().removeItem(item)
            except RuntimeError:
                pass
        items.clear()

    def draw_selection(self, rect):
        self._remove(self.overlay)
        self.selection = QRectF(rect).intersected(self.page_rect) if rect is not None else None
        if self.selection is None or self.selection.isEmpty():
            return
        blue = QColor("#3567ed")
        pen = QPen(blue, 1.5)
        pen.setCosmetic(True)
        if self.tool == "crop":
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)
            path.addRect(self.page_rect)
            path.addRect(self.selection)
            mask = self.scene().addPath(path, QPen(Qt.PenStyle.NoPen), QBrush(QColor(15, 30, 50, 45)))
            mask.setZValue(8)
            self.overlay.append(mask)
        border = self.scene().addRect(self.selection, pen, QBrush(QColor(53, 103, 237, 13)))
        border.setZValue(10)
        self.overlay.append(border)
        handle = 5 / max(.1, self._scale)
        for point in (self.selection.topLeft(), self.selection.topRight(), self.selection.bottomLeft(), self.selection.bottomRight()):
            item = self.scene().addRect(QRectF(point.x() - handle / 2, point.y() - handle / 2, handle, handle), pen, QBrush(Qt.GlobalColor.white))
            item.setZValue(11)
            self.overlay.append(item)

    def show_search(self, rectangles):
        self._remove(self.search_overlays)
        if not self.session:
            return
        for rect in rectangles:
            display = self.session.to_display(rect, self.page_index)
            item = self.scene().addRect(QRectF(display.x0, display.y0, display.width, display.height), QPen(Qt.PenStyle.NoPen), QBrush(QColor(255, 201, 40, 100)))
            item.setZValue(5)
            self.search_overlays.append(item)

    def _point(self, event):
        point = self.mapToScene(event.position().toPoint())
        return QPointF(max(0, min(self.page_rect.width(), point.x())), max(0, min(self.page_rect.height(), point.y())))

    def mousePressEvent(self, event):
        if not self.session:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.tool != "hand":
            point = self._point(event)
            if self.tool in ("edit", "note"):
                self.pointPicked.emit(point)
            else:
                self.drag_start = self.drag_end = point
                self.draw_selection(QRectF(point, point))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._middle is not None:
            delta = event.position() - self._middle
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            self._middle = event.position()
            event.accept()
            return
        if self.drag_start is not None:
            self.drag_end = self._point(event)
            self.draw_selection(QRectF(self.drag_start, self.drag_end).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._middle is not None:
            self._middle = None
            self.set_tool(self.tool)
            event.accept()
            return
        if self.drag_start is not None and event.button() == Qt.MouseButton.LeftButton:
            end = self._point(event)
            rect = QRectF(self.drag_start, end).normalized().intersected(self.page_rect)
            start = self.drag_start
            self.drag_start = self.drag_end = None
            if rect.width() * self._scale >= 3 and rect.height() * self._scale >= 3:
                self.draw_selection(rect)
                self.selectionMade.emit(rect, start, end)
            else:
                self.draw_selection(None)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoomRequested.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.session:
            self.resize_timer.start()
