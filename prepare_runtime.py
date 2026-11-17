"""Create a conventional, unpacked CPython application from collected dependencies.

The dependency collector is used at build time only. No frozen bootloader is
shipped; runtime code and the standard Python executable stay independently
replaceable. This also avoids executable-file locking in the deployment host.
"""
from pathlib import Path
import importlib.util
import marshal
import shutil
import struct
import sys
import types
from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader

source, destination, pyz_path = map(Path, sys.argv[1:4])
destination.mkdir(parents=True, exist_ok=True)
shutil.copytree(source / "_internal", destination / "_internal", dirs_exist_ok=True)
archive = ZlibArchiveReader(str(pyz_path))
count = 0
for name, entry in archive.toc.items():
    code = archive.extract(name)
    if not isinstance(code, types.CodeType):
        continue
    target = destination / "_internal" / Path(*name.split("."))
    target = target / "__init__.pyc" if entry[0] == 1 else target.with_suffix(".pyc")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(importlib.util.MAGIC_NUMBER + struct.pack("<III", 0, 0, 0) + marshal.dumps(code))
    count += 1
runtime = destination / "runtime"
runtime.mkdir(exist_ok=True)
# struct is a bootstrapping module held in the collector's outer executable,
# rather than PYZ/base_library.zip. In a standard interpreter it is a normal
# stdlib module and must be present on the isolated path explicitly.
import struct as stdlib_struct
shutil.copyfile(Path(stdlib_struct.__file__), destination / "_internal" / "struct.py")
for name in ("pythonw.exe", "python312.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
    file = Path(sys.base_prefix) / name
    if file.exists():
        shutil.copyfile(file, runtime / name)
(runtime / "python312._pth").write_text("..\\_internal\\base_library.zip\n..\\_internal\n", encoding="ascii")
app_source = Path(__file__).parent
for file in ("main.py", "core.py", "canvas.py", "dialogs.py", "style.py", "window.py", "qa.py", "version.py", "updates.py"):
    shutil.copyfile(app_source / file, destination / "_internal" / file)
license_file = Path(sys.base_prefix) / "LICENSE.txt"
if license_file.exists():
    shutil.copyfile(license_file, runtime / "Python-LICENSE.txt")
print(f"Prepared unpacked CPython runtime with {count} modules: {destination}")
