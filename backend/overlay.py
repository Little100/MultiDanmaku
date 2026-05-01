from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

_overlay_proc: subprocess.Popen | None = None


def launch_overlay(host: str = "127.0.0.1", port: int = 9800) -> bool:
    """Launch a native desktop overlay window using pywebview in a subprocess.

    Returns True if launched, False if already running.
    """
    global _overlay_proc

    if _overlay_proc and _overlay_proc.poll() is None:
        return False

    url = f"http://{host}:{port}/overlay"
    cmd = [sys.executable, "--_run_overlay", url]

    try:
        _overlay_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("overlay window launched (pid=%d)", _overlay_proc.pid)
        return True
    except Exception:
        logger.exception("failed to launch overlay subprocess")
        return False
