"""Build the standalone static S.PDF web application."""
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
try:
    build = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
except (OSError, subprocess.CalledProcessError):
    build = "development"
output = HERE / "dist"
output.mkdir(exist_ok=True)
icons = {file.stem:file.read_text(encoding="utf-8") for file in (ROOT / "assets" / "icons").glob("*.svg")}
(output / "icons.mjs").write_text("export const icons = " + json.dumps(icons, ensure_ascii=False) + ";\n", encoding="utf-8")
for name in ("index.html", "app.css", "app.mjs", "engine.mjs", "pdf-worker.mjs", "capture.mjs", "png.mjs"):
    text = (HERE / name).read_text(encoding="utf-8")
    if name == "index.html":
        text = text.replace('<meta charset="utf-8">', '<meta charset="utf-8"><meta name="spdf-build" content="'+build+'">')
        text = text.replace('href="app.css"', 'href="app.css?v='+build+'"').replace('src="app.mjs"', 'src="app.mjs?v='+build+'"')
    if name == "app.mjs": text = text.replace("'./icons.mjs'", "'./icons.mjs?v="+build+"'")
    if name == "pdf-worker.mjs": text = text.replace("'./engine.mjs'", "'./engine.mjs?v="+build+"'")
    if name in ("app.mjs", "engine.mjs"):
        for module in ("capture.mjs", "png.mjs"):
            text = text.replace("'./"+module+"'", "'./"+module+"?v="+build+"'")
    (output / name).write_text(text, encoding="utf-8")
shutil.copytree(HERE / "vendor", output / "vendor", dirs_exist_ok=True)
(output / "assets").mkdir(exist_ok=True)
shutil.copyfile(ROOT / "assets" / "spdf-symbol.svg", output / "assets" / "spdf-symbol.svg")
shutil.copyfile(ROOT / "LICENSE.txt", output / "assets" / "AGPL-3.0.txt")
(output / "version.json").write_text(json.dumps({"version":"3.4.0","build":build}), encoding="utf-8")
(output / ".nojekyll").write_text("", encoding="utf-8")
print(json.dumps({"directory":str(output), "build":build, "bytes":sum(file.stat().st_size for file in output.rglob('*') if file.is_file())}))
