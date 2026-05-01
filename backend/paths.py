"""Centralized path resolution for PyInstaller bundles and normal execution.

In a PyInstaller onefile bundle:
  - sys._MEIPASS = temp extraction dir (read-only bundled data lives here)
  - sys.executable = the .exe location (writable files go here)
In normal execution:
  - Everything resolves relative to the project root.
"""
from __future__ import annotations

import sys
import pathlib

IS_BUNDLED = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def exe_dir() -> pathlib.Path:
    return pathlib.Path(sys.executable).resolve().parent


def _bundled_base() -> pathlib.Path:
    return pathlib.Path(sys._MEIPASS)


def _dev_base() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def config_path() -> pathlib.Path:
    base = exe_dir() if IS_BUNDLED else _dev_base()
    return base / "config.json"


def upload_dir() -> pathlib.Path:
    base = exe_dir() if IS_BUNDLED else _dev_base()
    return base / "frontend" / "uploads"


def bundled_frontend() -> pathlib.Path:
    base = _bundled_base() if IS_BUNDLED else _dev_base()
    return base / "frontend"
