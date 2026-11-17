from pathlib import Path
import sys
import zipfile

source = Path(__file__).resolve().parent
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as archive:
    for file in source.rglob("*"):
        if not file.is_file() or any(part in (".git", ".venv", "__pycache__", ".pytest_cache", "tmp", "output") for part in file.relative_to(source).parts):
            continue
        if file.suffix in (".exe", ".pyc", ".pyd", ".zip"):
            continue
        archive.write(file, "S.PDF/" + file.relative_to(source).as_posix())
print(sys.argv[1])
