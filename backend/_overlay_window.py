"""pywebview overlay window. Launched as a subprocess by overlay.py."""
import ctypes
import time
import threading


# Win32 constants
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002


def _set_window_alpha(hwnd: int, alpha: int) -> None:
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)


def _find_and_set_alpha(title: str, alpha: int = 200) -> None:
    time.sleep(1.5)
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if hwnd:
        _set_window_alpha(hwnd, alpha)


def run(url: str) -> None:
    """Create and display the overlay window. Blocks until closed."""
    import webview

    window = webview.create_window(
        title="MultiDanmaku",
        url=url,
        width=380,
        height=600,
        min_size=(250, 200),
        on_top=True,
        frameless=True,
        resizable=True,
        background_color="#0f0f0f",
    )
    threading.Thread(target=_find_and_set_alpha, args=("MultiDanmaku", 200), daemon=True).start()
    webview.start(debug=False)
