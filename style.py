from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer
from core import ASSETS

BLUE = "#3567ed"
_icons = {}


def icon(name, color="#68758a"):
    key = (name, color)
    if key in _icons:
        return _icons[key]
    path = ASSETS / "icons" / (name + ".svg")
    if not path.exists():
        return QIcon()
    content = path.read_text(encoding="utf-8").replace('stroke="currentColor"', f'stroke="{color}"')
    renderer = QSvgRenderer(QByteArray(content.encode()))
    pix = QPixmap(40, 40)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    value = QIcon(pix)
    _icons[key] = value
    return value


def stylesheet(dark=False):
    surface, work, ink, sub, line, hover, soft = (
        ("#191f2a", "#101620", "#edf1f9", "#abb6c9", "#303847", "#252d3b", "#26375d") if dark else
        ("#ffffff", "#e9edf4", "#202c42", "#68758a", "#e4e8ef", "#f4f6fa", "#edf2ff")
    )
    accent_text = "#a7bdff" if dark else BLUE
    return f"""
    QWidget {{ color:{ink}; font-family:'Segoe UI','Malgun Gothic'; font-size:12px; }}
    QMainWindow, QDialog, QMessageBox {{ background:{surface}; }}
    QWidget#appRoot {{ background:{surface}; border:1px solid {line}; }}
    QWidget#titleBar {{ background:{surface}; border-bottom:1px solid {line}; }}
    QLabel#brand {{ font-size:20px; font-weight:700; letter-spacing:-1px; }}
    QLabel#tagline, QLabel[muted="true"] {{ color:{sub}; }}
    QLabel#sectionTitle {{ font-size:15px; font-weight:600; padding:3px 0 9px; }}
    QLabel#resolution {{ font-size:18px; font-weight:600; padding:12px; background:{hover}; border-radius:6px; }}
    QLabel#hint {{ color:{sub}; font-size:11px; }}
    QLabel#statusLabel {{ font-size:11px; color:{sub}; }}
    QFrame#tabsFrame {{ background:{hover}; border-bottom:1px solid {line}; }}
    QTabBar::tab {{ background:{hover}; color:{sub}; padding:12px 16px; min-width:125px; max-width:260px; border-top:2px solid transparent; border-top-left-radius:7px; border-top-right-radius:7px; }}
    QTabBar::tab:selected {{ background:{surface}; color:{ink}; border-top:2px solid {BLUE}; }}
    QTabBar::tab:hover {{ background:{soft}; }}
    QFrame#modeBar, QFrame#contextBar, QFrame#footer {{ background:{surface}; border-bottom:1px solid {line}; }}
    QFrame#footer {{ border-top:1px solid {line}; border-bottom:none; }}
    QToolButton {{ padding:8px 11px; border:0; border-radius:5px; background:transparent; }}
    QToolButton:hover {{ background:{hover}; }}
    QToolButton:checked {{ background:{soft}; color:{accent_text}; }}
    QToolButton:disabled, QPushButton:disabled {{ color:{sub}; }}
    QToolButton#windowClose:hover {{ background:#d6555e; color:white; }}
    QPushButton {{ padding:9px 12px; border:1px solid {line}; border-radius:6px; background:{surface}; }}
    QPushButton:hover {{ background:{hover}; border-color:#9aabc7; }}
    QPushButton:checked {{ border-color:{BLUE}; background:{soft}; color:{accent_text}; }}
    QPushButton[primary="true"] {{ background:{BLUE}; border-color:{BLUE}; color:white; font-weight:600; }}
    QPushButton[primary="true"]:hover {{ background:#2857d3; }}
    QPushButton[primary="true"]:disabled {{ background:{hover}; border-color:{line}; color:{sub}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QFontComboBox {{ background:{surface}; border:1px solid {line}; border-radius:5px; padding:7px; selection-background-color:{BLUE}; selection-color:white; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color:{BLUE}; }}
    QSpinBox QLineEdit, QDoubleSpinBox QLineEdit, QComboBox QLineEdit {{ padding:0; border:0; background:transparent; }}
    QComboBox QAbstractItemView {{ background:{surface}; color:{ink}; selection-background-color:{soft}; selection-color:{ink}; }}
    QListWidget, QTreeWidget {{ background:{surface}; border:none; outline:0; }}
    QListWidget::item {{ padding:6px; border:1px solid transparent; border-radius:5px; }}
    QListWidget::item:selected {{ border:1px solid {BLUE}; background:{soft}; color:{accent_text}; }}
    QListWidget::item:hover {{ background:{hover}; }}
    QListWidget#pageGallery {{ background:{work}; }}
    QGraphicsView#pdfCanvas {{ background:{work}; border:0; }}
    QFrame#sidebar {{ background:{surface}; border-right:1px solid {line}; }}
    QFrame#inspector {{ background:{surface}; border-left:1px solid {line}; }}
    QWidget#inspectorContent {{ background:{surface}; }}
    QFrame#compareHeader {{ background:{surface}; border-bottom:1px solid {line}; }}
    QStackedWidget#welcomeStack, QWidget#welcome {{ background:{work}; }}
    QScrollArea {{ border:none; background:{surface}; }}
    QScrollBar:vertical {{ width:10px; background:{hover}; margin:0; }}
    QScrollBar::handle:vertical {{ background:#a9b5c7; min-height:30px; border-radius:4px; margin:2px; }}
    QScrollBar:horizontal {{ height:10px; background:{hover}; }}
    QScrollBar::handle:horizontal {{ background:#a9b5c7; min-width:30px; border-radius:4px; margin:2px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
    QSplitter::handle {{ background:{line}; width:1px; height:1px; }}
    QMenu {{ background:{surface}; border:1px solid {line}; padding:5px; }}
    QMenu::item {{ padding:7px 22px; }}
    QMenu::item:selected {{ background:{soft}; }}
    QToolTip {{ background:{ink}; color:{surface}; border:0; padding:5px; }}
    QCheckBox {{ spacing:7px; }}
    QGroupBox {{ border:1px solid {line}; border-radius:6px; margin-top:12px; padding-top:14px; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 4px; }}
    """
