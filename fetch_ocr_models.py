"""Download the pinned upstream OCR models needed for a clean source build."""
import hashlib
import urllib.request
from pathlib import Path

COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
MODELS = {
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "kor": "6b85e11d9bbf07863b97b3523b1b112844c43e713df8b66418a081fd1060b3b2",
}
directory = Path(__file__).resolve().parent / "assets" / "tessdata"
directory.mkdir(parents=True, exist_ok=True)
for language, expected in MODELS.items():
    path = directory / f"{language}.traineddata"
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        continue
    url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{COMMIT}/{language}.traineddata"
    with urllib.request.urlopen(url, timeout=60) as response:
        content = response.read(10 * 1024 * 1024)
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError(f"OCR model checksum differs: {language}")
    path.write_bytes(content)
    print(f"Prepared verified OCR model: {language}")
