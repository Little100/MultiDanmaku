from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time

logger = logging.getLogger(__name__)

_overlay_proc: subprocess.Popen | None = None
_last_launch_time: float = 0


def _drain_stderr(proc: subprocess.Popen) -> None:
    """Read stderr from the overlay subprocess and log any output."""
    try:
        for line in proc.stderr:  # type: ignore[union-attr]
            text = line.decode(errors="replace").rstrip()
            if text:
                logger.error("overlay subprocess: %s", text)
    except Exception:
        pass


def launch_overlay(host: str = "127.0.0.1", port: int = 9800) -> bool:
    """Launch a native desktop overlay window using pywebview in a subprocess.

    Returns True if launched, False if already running.
    """
    global _overlay_proc, _last_launch_time

    if _overlay_proc and _overlay_proc.poll() is None:
        return False

    # Prevent rapid re-launch (e.g. double-click)
    now = time.time()
    if now - _last_launch_time < 3:
        if _overlay_proc and _overlay_proc.poll() is not None:
            logger.warning("overlay exited too quickly (code=%s), skipping re-launch", _overlay_proc.returncode)
        return False

    url = f"http://{host}:{port}/overlay"
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--_run_overlay", url]
    else:
        cmd = [sys.executable, "-m", "backend", "--_run_overlay", url]

    try:
        _overlay_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _last_launch_time = now
        logger.info("overlay window launched (pid=%d)", _overlay_proc.pid)
        # Drain stderr in background so we can see crash errors
        threading.Thread(target=_drain_stderr, args=(_overlay_proc,), daemon=True).start()
        return True
    except Exception:
        logger.exception("failed to launch overlay subprocess")
        return False
