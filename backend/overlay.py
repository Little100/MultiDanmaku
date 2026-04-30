from __future__ import annotations

import logging
import subprocess
import sys
import pathlib

logger = logging.getLogger(__name__)

_overlay_proc: subprocess.Popen | None = None


def launch_overlay(host: str = "127.0.0.1", port: int = 9800) -> bool:
    """Launch a native desktop overlay window using pywebview in a subprocess.

    Returns True if launched, False if already running.
    """
    global _overlay_proc

    if _overlay_proc and _overlay_proc.poll() is None:
        return False

    script = pathlib.Path(__file__).resolve().parent / "_overlay_window.py"
    url = f"http://{host}:{port}/overlay"

    _overlay_proc = subprocess.Popen(
        [sys.executable, str(script), url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("overlay window launched (pid=%d)", _overlay_proc.pid)
    return True
