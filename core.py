"""S.PDF document operations. Documents are edited in private working copies.

Copyright 2026 S.PDF contributors. SPDX-License-Identifier: AGPL-3.0-or-later
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

os.environ.setdefault("OMP_THREAD_LIMIT", "2")
import pymupdf as pdf

from version import VERSION
MAX_CAPTURE_PIXELS = 100_000_000
ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"


class PdfError(Exception):
    pass


class PasswordRequired(PdfError):
    pass


class Cancelled(PdfError):
    pass


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2)
    try:
        if path.read_text(encoding="utf-8") == content:
            return
    except OSError:
        pass
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(content, encoding="utf-8")
        atomic_replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_replace(source, destination):
    # Windows indexers and virus scanners can briefly hold newly written files.
    for attempt in range(8):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(.025 * (attempt + 1))


def data_dir() -> Path:
    root = Path(os.environ.get("SPDF_DATA_DIR", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "S.PDF"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def parse_pages(expression: str, count: int) -> list[int]:
    """User facing 1-based ranges -> ordered unique 0-based pages."""
    expression = expression.strip().replace("，", ",").replace("–", "-").replace("~", "-")
    if expression.lower() in ("", "all", "전체", "모두", "*"):
        return list(range(count))
    result = []
    for token in expression.split(","):
        try:
            pair = token.strip().split("-")
            if len(pair) == 1:
                begin = end = int(pair[0])
            elif len(pair) == 2:
                begin, end = map(int, pair)
            else:
                raise ValueError
            if not 1 <= begin <= end <= count:
                raise ValueError
        except ValueError:
            raise PdfError(f"페이지는 1~{count} 범위로 입력해주세요. 예: 1,3-5,8") from None
        for page in range(begin - 1, end):
            if page not in result:
                result.append(page)
    if not result:
        raise PdfError("페이지를 한 개 이상 선택해주세요.")
    return result


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 100000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise PdfError("저장할 이름을 만들 수 없습니다.")


def tessdata_path():
    """Tesseract's Windows narrow-path IO needs ASCII or a short path."""
    source = ASSETS / "tessdata"
    if sys.platform == "win32":
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(str(source), buffer, len(buffer)) and buffer.value.isascii():
            return buffer.value
        target = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "S.PDF" / "tessdata"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("kor.traineddata", "eng.traineddata"):
            if not (target / name).exists() or (target / name).stat().st_size != (source / name).stat().st_size:
                shutil.copyfile(source / name, target / name)
        if str(target).isascii():
            return str(target)
        if ctypes.windll.kernel32.GetShortPathNameW(str(target), buffer, len(buffer)) and buffer.value.isascii():
            return buffer.value
        raise PdfError("문자 인식 언어 파일의 경로를 읽을 수 없습니다. 영문 경로에 프로그램을 설치해주세요.")
    return str(source)


def normalized_toc(toc):
    result, level = [], 0
    for entry in toc:
        if len(entry) < 3 or entry[2] < 1:
            continue
        current = max(1, min(int(entry[0]), level + 1))
        result.append([current, str(entry[1]), int(entry[2])])
        level = current
    return result


def font_path(family="맑은 고딕", bold=False, italic=False) -> Path | None:
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    defaults = {
        "맑은 고딕": "malgunbd.ttf" if bold else "malgun.ttf",
        "Malgun Gothic": "malgunbd.ttf" if bold else "malgun.ttf",
        "Arial": "arialbi.ttf" if bold and italic else "arialbd.ttf" if bold else "ariali.ttf" if italic else "arial.ttf",
        "Segoe UI": "segoeuib.ttf" if bold else "segoeui.ttf",
        "돋움": "gulim.ttc", "굴림": "gulim.ttc", "바탕": "batang.ttc",
    }
    candidate = fonts / defaults.get(family, "")
    if candidate.is_file():
        return candidate
    if sys.platform == "win32":
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                    for index in range(winreg.QueryInfoKey(key)[1]):
                        name, filename, _ = winreg.EnumValue(key, index)
                        if family.casefold() in name.casefold() and ("bold" in name.casefold()) == bold:
                            candidate = Path(filename)
                            if not candidate.is_absolute():
                                candidate = fonts / candidate
                            if candidate.is_file():
                                return candidate
            except OSError:
                pass
    fallback = fonts / ("malgunbd.ttf" if bold else "malgun.ttf")
    return fallback if fallback.is_file() else None


def _save_document(document, destination: Path, password="", permissions=4095, optimize=True):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name("." + destination.stem + "." + uuid.uuid4().hex + ".pdf")
    try:
        options = dict(garbage=4 if optimize else 0, deflate=True, use_objstms=1)
        if password:
            options.update(encryption=pdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password, permissions=permissions)
        else:
            options["encryption"] = pdf.PDF_ENCRYPT_NONE
        document.save(str(temp), **options)
        with pdf.open(temp) as check:
            if check.needs_pass and not check.authenticate(password):
                raise PdfError("저장한 파일의 암호를 확인하지 못했습니다.")
            if len(check) != len(document):
                raise PdfError("저장한 파일의 페이지 수가 일치하지 않습니다.")
        atomic_replace(temp, destination)
    except PermissionError as error:
        raise PdfError("파일을 저장할 수 없습니다. 다른 프로그램에서 열려 있는지, 저장 권한이 있는지 확인해주세요.") from error
    finally:
        temp.unlink(missing_ok=True)


class Session:
    """Replayable edit history avoids huge per-edit snapshots on image-heavy PDFs.

    PyMuPDF 2.1 native journalling currently raises during text insertion. This
    independent command history also makes automatic recovery deterministic.
    """
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.id = self.folder.name
        self.doc = None
        self.path = None
        self.name = "새 문서.pdf"
        self.password = ""
        self.was_encrypted = False
        self.permissions = 4095
        self.editable = True
        self.actions = []
        self.cursor = 0
        self.saved_hash = None
        self.page = 0
        self.zoom = "page"
        self.scroll = [0, 0]
        self.revision = 0
        self.folder.mkdir(parents=True, exist_ok=True)

    @classmethod
    def open(cls, path, password="", root=None):
        path = Path(path).resolve()
        if not path.is_file():
            raise PdfError("PDF 파일을 찾을 수 없습니다.")
        session = cls(Path(root or data_dir() / "sessions") / uuid.uuid4().hex)
        try:
            with pdf.open(path) as source:
                if not source.is_pdf or len(source) == 0:
                    raise PdfError("페이지가 있는 PDF 문서를 선택해주세요.")
                session.was_encrypted = bool(source.needs_pass)
                auth = source.authenticate(password) if source.needs_pass else 4
                if not auth:
                    raise PasswordRequired("PDF 암호가 필요하거나 암호가 올바르지 않습니다.")
                session.permissions = source.permissions
                session.editable = bool(auth & 4 or source.permissions & pdf.PDF_PERM_MODIFY)
                if session.was_encrypted:
                    source.save(session.folder / "base.pdf", encryption=pdf.PDF_ENCRYPT_NONE)
                else:
                    shutil.copyfile(path, session.folder / "base.pdf")
            session.doc = pdf.open(session.folder / "base.pdf")
            session.path, session.name, session.password = str(path), path.name, password
            session.saved_hash = session.state_hash()
            session.persist()
            return session
        except Exception:
            session.close()
            shutil.rmtree(session.folder, ignore_errors=True)
            raise

    @classmethod
    def from_document(cls, document, name="새 문서.pdf", root=None):
        session = cls(Path(root or data_dir() / "sessions") / uuid.uuid4().hex)
        try:
            document.save(session.folder / "base.pdf", garbage=3, deflate=True)
            session.doc = pdf.open(session.folder / "base.pdf")
            session.name = name
            session.persist()
            return session
        except Exception:
            session.close()
            shutil.rmtree(session.folder, ignore_errors=True)
            raise

    @classmethod
    def restore(cls, folder, password=""):
        session = cls(Path(folder))
        meta = read_json(session.folder / "session.json")
        if not meta:
            raise PdfError("자동 복구 정보를 읽을 수 없습니다.")
        for key in ("path", "name", "was_encrypted", "permissions", "editable", "actions", "cursor", "saved_hash", "page", "zoom", "scroll"):
            if key in meta:
                setattr(session, key, meta[key])
        session.password = password
        session.rebuild()
        return session

    @property
    def count(self):
        return len(self.doc) if self.doc else 0

    @property
    def dirty(self):
        return self.saved_hash != self.state_hash()

    def state_hash(self):
        return hashlib.sha256(json.dumps([a["id"] for a in self.actions[:self.cursor]]).encode()).hexdigest()

    def persist(self):
        atomic_json(self.folder / "session.json", {key: getattr(self, key) for key in (
            "path", "name", "was_encrypted", "permissions", "editable", "actions", "cursor", "saved_hash", "page", "zoom", "scroll")})

    def resource(self, relative):
        path = (self.folder / relative).resolve()
        if not path.is_relative_to(self.folder.resolve()):
            raise PdfError("작업 파일 경로가 올바르지 않습니다.")
        return path

    def cache_font(self, family, bold=False, italic=False):
        source = font_path(family, bold, italic)
        if not source:
            return None
        relative = "fonts/" + hashlib.sha1(str(source).encode()).hexdigest() + source.suffix
        target = self.resource(relative)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        return relative

    def command(self, label, **command):
        if not self.editable:
            raise PdfError("이 PDF에는 수정 권한이 없습니다. 소유자 암호로 다시 열어주세요.")
        command.update(id=uuid.uuid4().hex, label=label)
        old_actions, old_cursor = self.actions, self.cursor
        try:
            self._apply(command)
            self.actions = self.actions[:self.cursor] + [command]
            self.cursor += 1
            self.revision += 1
            self.page = max(0, min(self.page, self.count - 1))
            self.persist()
        except Exception:
            self.actions, self.cursor = old_actions, old_cursor
            self.rebuild()
            raise

    def rebuild(self):
        self.close()
        self.doc = pdf.open(self.folder / "base.pdf")
        try:
            for action in self.actions[:self.cursor]:
                self._apply(action)
        except Exception:
            self.close()
            raise
        self.page = max(0, min(self.page, self.count - 1))
        self.revision += 1

    def undo(self):
        if self.cursor:
            self.cursor -= 1
            try:
                self.rebuild()
            except Exception:
                self.cursor += 1
                self.rebuild()
                raise
            self.persist()

    def redo(self):
        if self.cursor < len(self.actions):
            self._apply(self.actions[self.cursor])
            self.cursor += 1
            self.revision += 1
            self.persist()

    def _apply(self, action):
        kind = action["kind"]
        if kind == "order":
            order = action["order"]
            if not order or len(set(order)) != len(order) or any(p < 0 or p >= self.count for p in order):
                raise PdfError("페이지 순서가 올바르지 않습니다.")
            toc = self.doc.get_toc()
            mapping = {old: new + 1 for new, old in enumerate(order)}
            self.doc.select(order)
            toc = [[level, title, mapping[page - 1]] for level, title, page in toc if page - 1 in mapping]
            self.doc.set_toc(normalized_toc(toc))
        elif kind == "rotate":
            for index in action["pages"]:
                page = self.doc[index]
                page.set_rotation((page.rotation + action["angle"]) % 360)
        elif kind == "append":
            toc = self.doc.get_toc()
            for item in action["files"]:
                with pdf.open(self.resource(item["resource"])) as other:
                    offset = self.count
                    self.doc.insert_pdf(other)
                    toc.append([1, item["name"], offset + 1])
                    toc.extend([[min(level + 1, 20), title, page + offset] for level, title, page in other.get_toc() if page > 0])
            self.doc.set_toc(normalized_toc(toc))
        elif kind == "toc":
            self.doc.set_toc(normalized_toc(action["toc"]))
        elif kind == "text":
            self._apply_text(action)
        elif kind == "annot":
            page = self.doc[action["page"]]
            rect = pdf.Rect(action["rect"])
            color = tuple(action["color"])
            shape = action["shape"]
            if shape == "highlight":
                annot = page.add_highlight_annot(rect)
                annot.set_colors(stroke=color)
                annot.set_opacity(.35)
            elif shape == "rectangle":
                annot = page.add_rect_annot(rect)
                annot.set_colors(stroke=color)
                annot.set_border(width=1.5)
            elif shape == "arrow":
                annot = page.add_line_annot(pdf.Point(action["start"]), pdf.Point(action["end"]))
                annot.set_colors(stroke=color)
                annot.set_border(width=1.5)
                annot.set_line_ends(0, 4)
            elif shape == "note":
                annot = page.add_text_annot(rect.tl, action["text"])
                annot.set_colors(stroke=color)
            else:
                raise PdfError("알 수 없는 주석 도구입니다.")
            annot.set_info(title="S.PDF", content=action.get("text", ""))
            annot.update()
        elif kind == "delete_annot":
            page = self.doc[action["page"]]
            annots = list(page.annots() or [])
            if not 0 <= action["index"] < len(annots):
                raise PdfError("삭제할 주석을 찾지 못했습니다.")
            page.delete_annot(annots[action["index"]])
        elif kind == "ocr":
            for item in action["results"]:
                page = self.doc[item["page"]]
                for span in item["spans"]:
                    point, text, size = span
                    page.insert_text(point, text, fontsize=size, fontname="korea", render_mode=3)
        else:
            raise PdfError("지원하지 않는 복구 작업입니다.")

    def reorder(self, order):
        self.command("페이지 순서 변경", kind="order", order=list(order))

    def delete_pages(self, pages):
        remove = set(pages)
        if any(p < 0 or p >= self.count for p in remove):
            raise PdfError("삭제할 페이지가 올바르지 않습니다.")
        keep = [p for p in range(self.count) if p not in remove]
        if not keep:
            raise PdfError("모든 페이지를 삭제할 수 없습니다. 한 페이지 이상 남겨주세요.")
        self.command(f"{len(remove)}개 페이지 삭제", kind="order", order=keep)

    def rotate(self, pages, angle=90):
        self.command("페이지 회전", kind="rotate", pages=list(pages), angle=int(angle))

    def append(self, sources):
        files = []
        for source in sources:
            relative = "imports/" + uuid.uuid4().hex + ".pdf"
            target = self.resource(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(source, Session):
                source.doc.save(target, deflate=True)
                name = source.name
            else:
                with pdf.open(source) as other:
                    if other.needs_pass:
                        raise PasswordRequired("암호가 있는 파일은 먼저 S.PDF 탭으로 열어주세요.")
                    if not other.is_pdf or len(other) == 0:
                        raise PdfError("병합할 PDF를 확인해주세요.")
                    other.save(target, deflate=True)
                name = Path(source).name
            files.append({"resource": relative, "name": name})
        if files:
            self.command("PDF 파일 추가", kind="append", files=files)

    @staticmethod
    def merge(sources, name="통합문서.pdf", root=None):
        with pdf.open() as result:
            toc = []
            for source in sources:
                other = source.doc if isinstance(source, Session) else pdf.open(source)
                try:
                    if other.needs_pass:
                        raise PasswordRequired("암호가 있는 PDF는 먼저 탭으로 열어주세요.")
                    offset = len(result)
                    result.insert_pdf(other)
                    title = source.name if isinstance(source, Session) else Path(source).name
                    toc.append([1, title, offset + 1])
                    toc.extend([[level + 1, title, page + offset] for level, title, page in other.get_toc() if page > 0])
                finally:
                    if not isinstance(source, Session):
                        other.close()
            if not len(result):
                raise PdfError("합칠 파일을 추가해주세요.")
            result.set_toc(normalized_toc(toc))
            return Session.from_document(result, name, root)

    def extract(self, pages, destination):
        with pdf.open() as result:
            for index in pages:
                result.insert_pdf(self.doc, from_page=index, to_page=index)
            _save_document(result, Path(destination))

    def split(self, pages, chunk_size, directory, prefix=None):
        if chunk_size < 1:
            raise PdfError("묶을 페이지 수는 1 이상이어야 합니다.")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        for begin in range(0, len(pages), chunk_size):
            group = pages[begin:begin + chunk_size]
            target = unique_path(directory / f"{prefix or Path(self.name).stem}_{group[0]+1:04d}-{group[-1]+1:04d}.pdf")
            self.extract(group, target)
            paths.append(target)
        return paths

    def save(self, destination):
        if self.was_encrypted and not self.password:
            raise PasswordRequired("이 문서의 저장 암호를 먼저 설정해주세요.")
        _save_document(self.doc, Path(destination), self.password, self.permissions)
        self.path, self.name = str(Path(destination).resolve()), Path(destination).name
        self.saved_hash = self.state_hash()
        self.persist()

    def compress(self, destination, dpi=None, quality=85):
        work = self.folder / (uuid.uuid4().hex + "-compression.pdf")
        try:
            self.doc.save(work, deflate=True)
            with pdf.open(work) as result:
                if dpi:
                    result.rewrite_images(dpi_threshold=int(dpi * 1.15), dpi_target=int(dpi), quality=quality, bitonal=False)
                _save_document(result, Path(destination), self.password, self.permissions)
            return Path(destination).stat().st_size
        finally:
            work.unlink(missing_ok=True)

    def display_rect(self, page=None):
        return self.doc[self.page if page is None else page].rect

    def to_pdf(self, rect, page=None):
        current = self.doc[self.page if page is None else page]
        return pdf.Rect(rect) * current.derotation_matrix

    def to_display(self, rect, page=None):
        current = self.doc[self.page if page is None else page]
        return pdf.Rect(rect) * current.rotation_matrix

    def render(self, page=None, dpi=110, clip=None, max_pixels=MAX_CAPTURE_PIXELS):
        index = self.page if page is None else page
        current = self.doc[index]
        area = current.rect if clip is None else pdf.Rect(clip) & current.rect
        if area.is_empty or not math.isfinite(area.width + area.height):
            raise PdfError("표시할 영역을 선택해주세요.")
        if math.ceil(area.width * dpi / 72) * math.ceil(area.height * dpi / 72) > max_pixels:
            raise PdfError("이미지가 너무 큽니다. 해상도를 낮추거나 더 작은 영역을 선택해주세요. (최대 1억 픽셀)")
        return current.get_pixmap(dpi=max(36, int(dpi)), clip=area, alpha=False, annots=True)

    def capture(self, destination=None, page=None, dpi=300, clip=None, kind="png", quality=95):
        image = self.render(page, dpi, clip)
        image.set_dpi(dpi, dpi)
        data = image.tobytes("jpeg", jpg_quality=quality) if kind.lower() in ("jpg", "jpeg") else image.tobytes("png")
        if destination:
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                temp.write_bytes(data)
                atomic_replace(temp, destination)
            finally:
                temp.unlink(missing_ok=True)
        return data, (image.width, image.height)

    def batch_capture(self, pages, directory, dpi=300, normalized_clip=None, kind="png", progress=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        output = []
        for position, index in enumerate(pages):
            if progress and progress(position, len(pages), f"{index + 1}페이지 캡처") is False:
                break
            page = self.doc[index]
            clip = None
            if normalized_clip:
                x0, y0, x1, y1 = normalized_clip
                clip = pdf.Rect(x0 * page.rect.width, y0 * page.rect.height, x1 * page.rect.width, y1 * page.rect.height)
            target = unique_path(directory / f"{Path(self.name).stem}_{index+1:04d}.{kind}")
            self.capture(target, index, dpi, clip, kind)
            output.append(target)
        return output

    def find(self, text, progress=None):
        found = []
        if not text.strip():
            return found
        for index in range(self.count):
            if progress and progress(index, self.count, f"{index + 1}페이지 검색") is False:
                break
            page = self.doc[index]
            for rect in page.search_for(text):
                found.append((index, list(rect), page.get_textbox(rect + (-20, -3, 80, 3)).strip()))
        return found

    def selected_text(self, display_rect):
        return self.doc[self.page].get_textbox(self.to_pdf(display_rect)).strip()

    def pick_text(self, display_point):
        page = self.doc[self.page]
        point = pdf.Point(display_point) * page.derotation_matrix
        candidates = []
        for block in page.get_text("dict", flags=pdf.TEXT_PRESERVE_WHITESPACE)["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    rect = pdf.Rect(span["bbox"])
                    if span["text"].strip() and point in rect + (-2, -2, 2, 2):
                        item = dict(span)
                        item["direction"] = line.get("dir", (1, 0))
                        candidates.append(item)
        return min(candidates, key=lambda s: pdf.Rect(s["bbox"]).get_area()) if candidates else None

    def edit_text(self, rect, text, size=12, family="맑은 고딕", bold=False, italic=False, color=(0, 0, 0), replace=False, clear_image=False, origin=None, direction=None):
        if not text.strip():
            raise PdfError("넣을 글자를 입력해주세요.")
        if direction and (abs(direction[0] - 1) > .01 or abs(direction[1]) > .01):
            raise PdfError("기울거나 세로로 배치된 원본 글자는 직접 수정할 수 없습니다. 새 텍스트 추가 도구를 사용해주세요.")
        font = self.cache_font(family, bold, italic)
        self.command("글자 수정" if replace else "텍스트 추가", kind="text", page=self.page, rect=list(pdf.Rect(rect)), text=text, size=float(size), font=font, bold=bool(bold), color=list(color), replace=bool(replace), clear_image=bool(clear_image), origin=list(origin) if origin else None)

    def _apply_text(self, action):
        page = self.doc[action["page"]]
        rect = pdf.Rect(action["rect"])
        if rect.is_empty or rect.is_infinite or not all(math.isfinite(value) for value in rect):
            raise PdfError("텍스트를 넣을 영역을 선택해주세요.")
        fontfile = str(self.resource(action["font"])) if action.get("font") else None
        fontname = "spdf" + hashlib.sha1((fontfile or "").encode()).hexdigest()[:8] if fontfile else "korea"
        size = action["size"]
        kwargs = dict(fontsize=size, fontname=fontname, fontfile=fontfile, color=tuple(action["color"]))
        origin = action.get("origin")
        single = origin and "\n" not in action["text"]
        if single:
            font = pdf.Font(fontfile=fontfile) if fontfile else pdf.Font("korea")
            if font.text_length(action["text"], fontsize=size) > rect.width + 2:
                raise PdfError("새 글자가 선택 영역보다 깁니다. 글자 크기를 줄이거나 새 텍스트 영역을 넓혀주세요.")
        else:
            with pdf.open() as scratch:
                scratch.new_page(width=page.mediabox.width, height=page.mediabox.height)
                result = scratch[0].insert_textbox(rect, action["text"], **kwargs)
                if result < -0.01:
                    raise PdfError("글자가 영역 안에 들어가지 않습니다. 영역을 넓히거나 글자 크기를 줄여주세요.")
        if action["replace"]:
            # Remove text content; never simulate an edit with an opaque cover.
            page.add_redact_annot(rect + (.1, .1, -.1, -.1), fill=(1, 1, 1) if action["clear_image"] else None, cross_out=False)
            page.apply_redactions(images=2 if action["clear_image"] else 0, graphics=0, text=0)
        if single:
            page.insert_text(pdf.Point(origin), action["text"], **kwargs)
        else:
            page.insert_textbox(rect, action["text"], **kwargs)

    def annotate(self, shape, display_rect, color=(1, .8, 0), text="", start=None, end=None):
        rect = self.to_pdf(display_rect)
        page = self.doc[self.page]
        self.command("주석 추가", kind="annot", shape=shape, page=self.page, rect=list(rect), color=list(color), text=text,
                     start=list(pdf.Point(start) * page.derotation_matrix) if start else list(rect.tl),
                     end=list(pdf.Point(end) * page.derotation_matrix) if end else list(rect.br))

    def add_bookmark(self, title):
        toc = self.doc.get_toc()
        toc.append([1, title, self.page + 1])
        self.command("북마크 추가", kind="toc", toc=toc)

    def ocr(self, pages, language="kor+eng", dpi=200, progress=None):
        results = []
        for position, index in enumerate(pages):
            if progress and progress(position, len(pages), f"{index + 1}페이지 글자 인식") is False:
                raise Cancelled("문자 인식을 취소했습니다. 문서는 변경하지 않았습니다.")
            page = self.doc[index]
            # Existing text is retained. OCR is useful for image-only pages.
            if len(page.get_text().strip()) > 4:
                continue
            textpage = page.get_textpage_ocr(language=language, dpi=dpi, full=True, tessdata=tessdata_path())
            spans = []
            for block in textpage.extractDICT().get("blocks", []):
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        if span["text"].strip():
                            spans.append([list(span["origin"]), span["text"], float(span["size"])])
            if spans:
                results.append({"page": index, "spans": spans})
        if results:
            self.command("한국어·영어 문자 인식", kind="ocr", results=results)
        return len(results)

    def close(self):
        if self.doc is not None:
            self.doc.close()
            self.doc = None
