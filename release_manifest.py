"""Create release metadata after the final installer has been built."""
import hashlib
import json
import sys
from pathlib import Path
from version import VERSION, REPOSITORY

installer = Path(sys.argv[1])
digest = hashlib.sha256()
with installer.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
value = dict(schema=1, app="S.PDF", repository=REPOSITORY, version=VERSION,
             size=installer.stat().st_size, sha256=digest.hexdigest())
(installer.parent / "update.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
print(f"Release metadata: S.PDF {VERSION}")
