"""Standalone pywebview overlay window. Launched as a subprocess."""
import sys
import ctypes
import time
import threading

try:
    import webview
except ImportError:
    sys.exit(0)

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9800/overlay"

# Win32 constants
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002

def set_window_alpha(hwnd, alpha):
    """Set window transparency via Win32 API (0-255)."""
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)

def find_and_set_alpha(title, alpha=200):
    """Find the pywebview window by title and set its alpha."""
    time.sleep(1.5)  # wait for window to fully render
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if hwnd:
        set_window_alpha(hwnd, alpha)

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

# Apply transparency after window is created
threading.Thread(target=find_and_set_alpha, args=("MultiDanmaku", 200), daemon=True).start()
webview.start(debug=False)
