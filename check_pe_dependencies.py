from pathlib import Path
import sys
import pefile
root = Path(sys.argv[1])
lookup = {}
for path in root.rglob("*"):
    if path.suffix.lower() in (".dll", ".pyd"):
        lookup.setdefault(path.name.lower(), []).append(path)
exports = {}
def exported(path):
    if path not in exports:
        module = pefile.PE(str(path), fast_load=True, max_symbol_exports=1000000)
        module.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
        exports[path] = {item.name for item in getattr(module, 'DIRECTORY_ENTRY_EXPORT', ()).symbols} if hasattr(module, 'DIRECTORY_ENTRY_EXPORT') else set()
        module.close()
    return exports[path]
for path in root.rglob("*"):
    if path.suffix.lower() not in (".dll", ".pyd"):
        continue
    module=pefile.PE(str(path), fast_load=True)
    module.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
    for entry in getattr(module, 'DIRECTORY_ENTRY_IMPORT', []):
        name=entry.dll.decode().lower()
        candidates=lookup.get(name, [])
        if not candidates:
            continue
        for candidate in candidates:
            symbols=exported(candidate)
            missing=[item.name.decode() for item in entry.imports if item.name and item.name not in symbols]
            if missing:
                print(path.relative_to(root), '->', candidate.relative_to(root), ':', missing[:12])
    module.close()
