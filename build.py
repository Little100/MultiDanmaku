"""Build MultiDanmaku into a standalone .exe using PyInstaller.

Usage:
    pip install pyinstaller
    playwright install chromium   # browser must be installed before building
    python build.py

Output: dist/MultiDanmaku.exe
"""
import os
import pathlib
import shutil
import subprocess

import PyInstaller.__main__
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = pathlib.Path(__file__).resolve().parent

# -- Staging: copy only the frontend files needed at runtime into a temp dir --
FRONTEND = ROOT / "frontend"
STAGE = ROOT / "_build_frontend"

NEEDED = [
    "index.html",
    "admin.html",
    "admin.js",
    "app.js",
    "overlay.html",
    "templates",
]

if STAGE.exists():
    shutil.rmtree(STAGE)
STAGE.mkdir()
for name in NEEDED:
    src = FRONTEND / name
    if not src.exists():
        continue
    dst = STAGE / name
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)

# -- Collect webview submodules so pywebview backends are bundled --
webview_hidden = [f"--hidden-import={m}" for m in collect_submodules("webview")]

# -- Collect playwright driver (Node.js runtime + native binary) --
playwright_data = [f"--add-data={src};{dst}" for src, dst in collect_data_files("playwright")]

# -- Playwright browsers: install locally and bundle into exe --
BROWSERS_DIR = ROOT / ".playwright-browsers"
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
if not list(BROWSERS_DIR.glob("chromium-*/chrome-win/chrome.exe")):
    print("Installing Chromium for Playwright (this may take a few minutes)...")
    subprocess.run(
        ["playwright", "install", "chromium"],
        check=True,
    )

chrome_paths = list(BROWSERS_DIR.glob("chromium-*/chrome-win/chrome.exe"))
print(f"Bundling Playwright Chromium: {chrome_paths[0] if chrome_paths else 'NOT FOUND'}")

browser_data = [f"--add-data={BROWSERS_DIR};playwright/driver/package/.local-browsers"]

# -- Clean stale build artifacts --
for d in (ROOT / "build", ROOT / "dist", ROOT / "MultiDanmaku.spec"):
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    elif d.is_file():
        d.unlink(missing_ok=True)

try:
    PyInstaller.__main__.run([
        str(ROOT / "backend" / "__main__.py"),
        "--name=MultiDanmaku",
        "--onefile",
        "--console",
        f"--add-data={STAGE};frontend",
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
        # playwright driver data (Node.js runtime)
        *playwright_data,
        # playwright browser binaries
        *browser_data,
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build'}",
        f"--specpath={ROOT}",
    ])
finally:
    # Always clean up staging dir
    if STAGE.exists():
        shutil.rmtree(STAGE, ignore_errors=True)
