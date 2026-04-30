"""Build MultiDanmaku into a standalone .exe using PyInstaller.

Usage:
    pip install pyinstaller
    python build.py

Output: dist/MultiDanmaku.exe
"""
import PyInstaller.__main__
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

PyInstaller.__main__.run([
    str(ROOT / "backend" / "__main__.py"),
    "--name=MultiDanmaku",
    "--onefile",
    "--console",
    f"--add-data={ROOT / 'frontend'};frontend",
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
    f"--distpath={ROOT / 'dist'}",
    f"--workpath={ROOT / 'build'}",
    f"--specpath={ROOT}",
])
