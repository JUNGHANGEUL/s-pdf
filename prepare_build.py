"""Prepare branded installer sources, legal notices and a source archive."""
from pathlib import Path
import json
import shutil
import zipfile
import importlib.metadata
from version import VERSION

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent


def prepare():
    installer = HERE / "installer"
    for name in ("Setup.cs", "Uninstall.cs", "InstallFiles.cs"):
        if (installer / name).is_file():
            continue
        original = WORKSPACE / "pdf-viewer" / "src" / name
        if not original.exists():
            if not (installer / name).is_file():
                raise FileNotFoundError(f"Installer source missing: {name}")
            continue
        text = original.read_text(encoding="utf-8")
        for old, new in (("EasyPdfViewer", "S.PDF"), ("편한 PDF 뷰어", "S.PDF"), (".easy-pdf-viewer", ".spdf-install"), ("1.0.0.0", "2.0.0.0"), ("1.0.0", "2.0.0"), ("뷰어 실행", "S.PDF 실행")):
            text = text.replace(old, new)
        text = text.replace("PDF 열기 · 페이지 이동 · 확대/축소 · 화면 회전\\n인터넷 연결 없이 내 컴퓨터에서 사용합니다.", "탭 · 고화질 캡처 · 병합 · 페이지 편집 · 글자 수정\\n주석 · 비교 · 자동 복구 · 용량 줄이기 · 한국어 OCR")
        text = text.replace("Color.FromArgb(35, 85, 131)", "Color.FromArgb(53, 103, 237)").replace("Color.FromArgb(31, 62, 91)", "Color.FromArgb(32, 44, 66)")
        if name == "Setup.cs":
            text = text.replace('key.SetValue("EstimatedSize", 8500, RegistryValueKind.DWord);', 'key.SetValue("EstimatedSize", 250000, RegistryValueKind.DWord);')
            text = text.replace('key.SetValue("Publisher", "개인용 PDF 도구")', 'key.SetValue("Publisher", "S.PDF Contributors")')
            text = text.replace('key.SetValue("DisplayName", "S.PDF");', 'key.SetValue("DisplayName", "S.PDF");')
            text = text.replace('string exe = Path.Combine(InstallPath, "S.PDF.exe");', 'string exe = Path.Combine(InstallPath, "S.PDF.exe");\n            FileAssociations.Register(exe);')
        if name == "Uninstall.cs":
            text = text.replace('InstallFiles.RemoveOwned(path);', 'InstallFiles.RemoveOwned(path);\n        FileAssociations.Unregister(Path.Combine(path, "S.PDF.exe"));')
        (installer / name).write_text(text, encoding="utf-8-sig")
    original_manifest = WORKSPACE / "pdf-viewer" / "app.manifest"
    if original_manifest.exists():
        text = original_manifest.read_text(encoding="utf-8").replace("Local.SimplePdfViewer", "Local.SPDF.Setup").replace("1.0.0.0", VERSION + ".0")
        (installer / "app.manifest").write_text(text, encoding="utf-8")
    (installer / "BuildInfo.cs").write_text('internal static class BuildInfo { internal const string Version = "' + VERSION + '"; internal const string AssemblyVersion = "' + VERSION + '.0"; }\n', encoding="utf-8")
    licenses = HERE / "licenses"
    licenses.mkdir(exist_ok=True)
    for package in ("pymupdf", "PySide6-Essentials", "shiboken6"):
        dist = importlib.metadata.distribution(package)
        for file in dist.files or []:
            relative = str(file).replace("\\", "/")
            if ".dist-info/" in relative and ("licenses/" in relative or relative.endswith("COPYING")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    shutil.copyfile(source, licenses / (package + "-" + source.name))
    (HERE / "requirements.txt").write_text("PyMuPDF==2.1\nPySide6-Essentials==6.12.0\nPyInstaller==6.22.3\npytest==9.2.0\n", encoding="utf-8")
    return licenses


if __name__ == "__main__":
    print(prepare())
