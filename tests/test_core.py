import hashlib
import json
import random
import sys
from pathlib import Path

import pymupdf as pdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Session, PdfError, PasswordRequired, parse_pages, font_path, ASSETS


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "한글 파일 [원본].pdf"
    with pdf.open() as doc:
        for index in range(4):
            page = doc.new_page(width=400, height=300)
            page.insert_text((40, 60), f"PAGE {index + 1} HELLO WORLD", fontsize=18)
            page.draw_rect(pdf.Rect(40, 100, 180, 220), color=None, fill=(1, 0, 0))
            page.draw_rect(pdf.Rect(200, 100, 360, 220), color=None, fill=(0, 0, 1))
        doc.set_toc([[1, "First", 1], [1, "Last", 4]])
        doc.save(path)
    return path


@pytest.fixture
def session(source, tmp_path):
    result = Session.open(source, root=tmp_path / "sessions")
    yield result
    result.close()


def test_ranges():
    assert parse_pages("1,3-5,3", 7) == [0, 2, 3, 4]
    for text in ("0", "2-1", "x", "1-9", "1,,2"):
        with pytest.raises(PdfError):
            parse_pages(text, 7)


def test_pages_save_and_original_preserved(session, source, tmp_path):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    session.delete_pages([1])
    assert session.count == 3 and "PAGE 3" in session.doc[1].get_text()
    assert session.dirty
    session.undo()
    assert session.count == 4 and not session.dirty
    session.redo()
    session.reorder([2, 0, 1])
    assert "PAGE 4" in session.doc[0].get_text()
    session.rotate([0])
    assert session.doc[0].rotation == 90
    result = tmp_path / "변경 결과.pdf"
    session.save(result)
    assert not session.dirty
    with pdf.open(result) as check:
        assert len(check) == 3 and check[0].rotation == 90
        assert "PAGE 2" not in "".join(p.get_text() for p in check)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    session.undo()
    assert session.dirty and session.doc[0].rotation == 0
    session.redo()
    assert not session.dirty


def test_cannot_delete_all(session):
    with pytest.raises(PdfError):
        session.delete_pages(range(4))
    assert session.count == 4


def test_merge_uses_unsaved_edits(session, source, tmp_path):
    session.delete_pages([0, 1])
    merged = Session.merge([session, source], root=tmp_path / "merged")
    try:
        assert merged.count == 6
        assert "PAGE 3" in merged.doc[0].get_text()
        assert "PAGE 1" in merged.doc[2].get_text()
        assert len(merged.doc.get_toc()) >= 2
    finally:
        merged.close()


def test_append_and_recovery(session, source):
    session.append([source])
    session.delete_pages([0])
    session.add_bookmark("Current")
    folder = session.folder
    session.close()
    restored = Session.restore(folder)
    try:
        assert restored.count == 7
        assert "PAGE 2" in restored.doc[0].get_text()
        assert any(row[1] == "Current" for row in restored.doc.get_toc())
        restored.undo()
        assert not any(row[1] == "Current" for row in restored.doc.get_toc())
        restored.undo()
        assert restored.count == 8
    finally:
        restored.close()


def test_export_extract_split(session, tmp_path):
    path = tmp_path / "추출.pdf"
    session.extract([3, 1], path)
    with pdf.open(path) as doc:
        assert len(doc) == 2 and "PAGE 4" in doc[0].get_text()
    files = session.split(list(range(4)), 2, tmp_path / "split")
    assert len(files) == 2
    assert all(pdf.open(file).page_count == 2 for file in files)
    assert session.count == 4 and not session.dirty


def test_render_capture_pixels_dpi_and_rotated_clip(session, tmp_path):
    data, size = session.capture(tmp_path / "capture.png", dpi=144, clip=pdf.Rect(40, 100, 180, 220))
    assert size == (280, 240)
    image = pdf.Pixmap(data)
    assert image.pixel(100, 100) == (255, 0, 0)
    session.rotate([0])
    full = session.render(dpi=72)
    clip = pdf.Rect(20, 20, 100, 100)
    part = session.render(dpi=72, clip=clip)
    assert part.width == 80 and part.height == 80
    assert part.pixel(40, 40) == full.pixel(60, 60)
    with pytest.raises(PdfError):
        session.render(dpi=3000)


def test_batch_capture_and_no_overwrite(session, tmp_path):
    first = session.batch_capture([0, 2], tmp_path / "images", 72, (.1, .3, .4, .7))
    assert len(first) == 2 and all(p.exists() for p in first)
    second = session.batch_capture([0], tmp_path / "images", 72, (.1, .3, .4, .7))
    assert second[0] != first[0] and first[0].exists()


def test_search_and_text_replace(session, tmp_path):
    assert len(session.find("HELLO")) == 4
    span = session.pick_text((100, 54))
    assert span and "HELLO" in span["text"]
    session.edit_text(span["bbox"], "REPLACED", size=18, family="Arial", replace=True, origin=span["origin"])
    text = session.doc[0].get_text()
    assert "REPLACED" in text and "HELLO" not in text
    session.undo()
    assert "HELLO" in session.doc[0].get_text()
    session.redo()
    target = tmp_path / "edited.pdf"
    session.save(target)
    with pdf.open(target) as result:
        assert "REPLACED" in result[0].get_text() and "HELLO" not in result[0].get_text()


def test_long_text_rolls_back_without_losing_history(session):
    span = session.pick_text((100, 54))
    with pytest.raises(PdfError):
        session.edit_text(span["bbox"], "TOO LONG " * 30, size=18, family="Arial", replace=True, origin=span["origin"])
    assert "HELLO" in session.doc[0].get_text() and session.cursor == 0


def test_korean_text_add_and_annotation_roundtrip(session, tmp_path):
    session.edit_text(pdf.Rect(50, 230, 360, 290), "평택시 도로 정비계획", size=16)
    for shape in ("highlight", "rectangle", "arrow", "note"):
        session.annotate(shape, (40, 100, 180, 200), text="검토 메모")
    assert "평택시" in session.doc[0].get_text()
    target = tmp_path / "annotations.pdf"
    session.save(target)
    with pdf.open(target) as result:
        assert len(list(result[0].annots())) == 4
        assert "평택시" in result[0].get_text()


def test_password_open_and_save(tmp_path):
    path = tmp_path / "locked.pdf"
    with pdf.open() as doc:
        doc.new_page().insert_text((40, 40), "secret")
        doc.save(path, encryption=pdf.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="owner")
    with pytest.raises(PasswordRequired):
        Session.open(path, root=tmp_path / "sessions")
    session = Session.open(path, "owner", root=tmp_path / "sessions")
    try:
        session.save(tmp_path / "still-locked.pdf")
        with pdf.open(tmp_path / "still-locked.pdf") as result:
            assert result.needs_pass and result.authenticate("owner")
    finally:
        session.close()


def test_image_compression(tmp_path):
    source = tmp_path / "large.pdf"
    noise = random.Random(4).randbytes(1000 * 1000 * 3)
    image = pdf.Pixmap(pdf.csRGB, 1000, 1000, noise, False)
    with pdf.open() as doc:
        page = doc.new_page(width=250, height=250)
        page.insert_image(page.rect, pixmap=image)
        page.insert_text((10, 20), "KEEP TEXT")
        doc.save(source)
    session = Session.open(source, root=tmp_path / "sessions")
    try:
        target = tmp_path / "small.pdf"
        size = session.compress(target, dpi=96, quality=75)
        assert size < source.stat().st_size / 2
        with pdf.open(target) as result:
            assert "KEEP TEXT" in result[0].get_text()
        assert not session.dirty
    finally:
        session.close()


def test_ocr_english_and_korean(tmp_path):
    scanned = tmp_path / "scan.pdf"
    with pdf.open() as original:
        page = original.new_page(width=700, height=350)
        page.insert_text((40, 80), "HELLO WORLD", fontsize=38)
        page.insert_text((40, 170), "평택시 도로 정비계획", fontsize=30, fontfile=str(font_path()), fontname="testkr")
        image = page.get_pixmap(dpi=150)
        with pdf.open() as scan:
            scan.new_page(width=700, height=350).insert_image(page.rect, pixmap=image)
            scan.save(scanned)
    session = Session.open(scanned, root=tmp_path / "sessions")
    try:
        assert not session.doc[0].get_text().strip()
        assert session.ocr([0]) == 1
        text = session.doc[0].get_text()
        assert "HELLO" in text
        assert "평택" in text.replace(" ", "")
        target = tmp_path / "searchable.pdf"
        session.save(target)
        with pdf.open(target) as result:
            assert result[0].search_for("HELLO")
        session.undo()
        assert not session.doc[0].get_text().strip()
    finally:
        session.close()
