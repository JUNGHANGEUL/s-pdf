from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QSpinBox, QDialogButtonBox, QListWidget, QListWidgetItem, QAbstractItemView,
    QPushButton, QFileDialog, QCheckBox)


class RangeDialog(QDialog):
    def __init__(self, parent, title, count, default="", chunk=False, extra=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(430, 230)
        layout = QVBoxLayout(self)
        label = QLabel(f"페이지 범위 (1~{count})")
        layout.addWidget(label)
        self.range = QLineEdit(default or f"1-{count}")
        self.range.setPlaceholderText("예: 1,3-5,8")
        layout.addWidget(self.range)
        layout.addWidget(QLabel("쉼표와 하이픈으로 범위를 지정할 수 있습니다."))
        self.chunk = QSpinBox()
        self.chunk.setRange(1, count)
        if chunk:
            row = QHBoxLayout()
            row.addWidget(QLabel("파일 하나당 페이지 수"))
            row.addWidget(self.chunk)
            layout.addLayout(row)
        self.extra = QComboBox()
        if extra:
            self.extra.addItems(extra)
            layout.addWidget(self.extra)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MergeDialog(QDialog):
    def __init__(self, parent, sessions):
        super().__init__(parent)
        self.setWindowTitle("PDF 파일 합치기")
        self.resize(620, 470)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("합칠 파일을 추가한 뒤 끌어서 순서를 바꿔주세요."))
        self.files = QListWidget()
        self.files.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.files, 1)
        for session in sessions:
            self.add(session.name + f"  ·  {session.count}페이지" + (" · 수정됨" if session.dirty else ""), session)
        row = QHBoxLayout()
        add = QPushButton("파일 추가")
        add.clicked.connect(self.pick_files)
        remove = QPushButton("선택 파일 제외")
        remove.clicked.connect(lambda: [self.files.takeItem(self.files.row(i)) for i in self.files.selectedItems()])
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(QLabel("열려 있는 탭은 저장하지 않은 변경사항까지 합칩니다."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("새 문서로 합치기")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add(self, text, source):
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, source)
        self.files.addItem(item)

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "합칠 PDF 선택", "", "PDF 문서 (*.pdf)")
        for file in files:
            self.add(Path(file).name, file)

    def sources(self):
        return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]


class CompressionDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("PDF 용량 줄이기")
        self.resize(470, 270)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("문서의 용도에 맞는 압축 방식을 선택해주세요."))
        self.preset = QComboBox()
        self.preset.addItems(["무손실 최적화 · 글자와 이미지 품질 유지", "고화질 · 이미지 300dpi / JPG 품질 92", "균형 · 이미지 150dpi / JPG 품질 85", "작은 용량 · 이미지 96dpi / JPG 품질 75"])
        layout.addWidget(self.preset)
        label = QLabel("이미지 압축을 사용하면 이미지 품질이 낮아질 수 있습니다.\n글자와 벡터 도형은 유지하고 별도 PDF로 저장합니다.\n이미 최적화된 파일은 용량이 줄어들지 않을 수 있습니다.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.open_result = QCheckBox("저장 후 결과 파일 열기")
        self.open_result.setChecked(True)
        layout.addWidget(self.open_result)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self):
        return [(None, 100), (300, 92), (150, 85), (96, 75)][self.preset.currentIndex()]
