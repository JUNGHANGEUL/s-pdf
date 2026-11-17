"""Prepare pinned browser libraries. No package lifecycle scripts are executed."""
import base64
import hashlib
import io
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent.parent / "tmp" / "spdf-web-dependencies"
PACKAGES = {"mupdf": "1.28.6", "tesseract.js": "7.0.0", "tesseract.js-core": "7.0.0", "fflate": "0.8.2"}


def package(name, version):
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / (name + "-" + version)
    if (target / "package.json").exists():
        return target
    with urllib.request.urlopen(f"https://registry.npmjs.org/{name}/{version}", timeout=60) as response:
        meta = json.load(response)
    with urllib.request.urlopen(meta["dist"]["tarball"], timeout=90) as response:
        data = response.read()
    algorithm, expected = meta["dist"]["integrity"].split("-", 1)
    assert base64.b64encode(hashlib.new(algorithm, data).digest()).decode() == expected, name
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for entry in archive.getmembers():
            if not entry.isfile():
                continue
            relative = Path(entry.name).relative_to("package")
            destination = (target / relative).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError("Unsafe package path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.extractfile(entry).read())
    return target


if __name__ == "__main__":
    roots = {name:package(name, version) for name, version in PACKAGES.items()}
    vendor = HERE / "vendor"
    for name, location in (("mupdf", "dist"), ("tesseract.js", "dist"), ("tesseract.js-core", "."), ("fflate", "esm")):
        target = vendor / name
        target.mkdir(parents=True, exist_ok=True)
        for source in (roots[name] / location).rglob("*"):
            if not source.is_file() or source.suffix not in (".js", ".mjs", ".wasm", ".ts"):
                continue
            destination = target / source.relative_to(roots[name] / location)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        for source in roots[name].glob("*LICENSE*"):
            if source.is_file(): shutil.copyfile(source, target / source.name)
    models = vendor / "tessdata"
    models.mkdir(parents=True, exist_ok=True)
    for language in ("eng", "kor"):
        source = HERE.parent / "assets" / "tessdata" / (language + ".traineddata")
        shutil.copyfile(source, models / source.name)
    shutil.copyfile(HERE.parent / "assets" / "tessdata" / "LICENSE.txt", models / "LICENSE.txt")
    print(json.dumps({"vendor":str(vendor), "packages":PACKAGES}))
