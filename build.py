"""Build MultiDanmaku into a standalone .exe using PyInstaller.

Usage:
    pip install pyinstaller
    python build.py

Output: dist/MultiDanmaku.exe
"""
import pathlib
import shutil

import PyInstaller.__main__
from PyInstaller.utils.hooks import collect_submodules

ROOT = pathlib.Path(__file__).resolve().parent

# Only bundle the frontend files actually needed at runtime.
# Exclude: node_modules/, src/, tsconfig.json, package*.json, app.js.map
FRONTEND = ROOT / "frontend"
frontend_data_parts = [
    "index.html",
    "admin.html",
    "admin.js",
    "app.js",
    "overlay.html",
    "templates",
]
add_data_args = []
for part in frontend_data_parts:
    src = FRONTEND / part
    if src.exists():
        add_data_args.append(f"--add-data={src};frontend/{part}")

# Collect all webview submodules so pywebview backends are bundled
webview_hidden = [f"--hidden-import={m}" for m in collect_submodules("webview")]

# Clean stale build artifacts
for d in (ROOT / "build", ROOT / "dist", ROOT / "MultiDanmaku.spec"):
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    elif d.is_file():
        d.unlink(missing_ok=True)

PyInstaller.__main__.run([
    str(ROOT / "backend" / "__main__.py"),
    "--name=MultiDanmaku",
    "--onefile",
    "--console",
    *add_data_args,
    # uvicorn hidden imports
    "--hidden-import=uvicorn.logging",
    "--hidden-import=uvicorn.loops",
    "--hidden-import=uvicorn.loops.auto",
    "--hidden-import=uvicorn.protocols",
    "--hidden-import=uvicorn.protocols.http",
    "--hidden-import=uvicorn.protocols.http.auto",
    "--hidden-import=uvicorn.protocols.websockets",
    "--hidden-import=uvicorn.protocols.websockets.auto",
    "--hidden-import=uvicorn.lifespan",
    "--hidden-import=uvicorn.lifespan.on",
    # webview hidden imports
    *webview_hidden,
    f"--distpath={ROOT / 'dist'}",
    f"--workpath={ROOT / 'build'}",
    f"--specpath={ROOT}",
])
