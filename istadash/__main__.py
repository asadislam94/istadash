"""IstaDash desktop entry point — wraps the Flask app in a PyWebView window."""
from __future__ import annotations

import socket
import threading
import time
import urllib.request


def _find_free_port() -> int:
    """Bind to port 0 to let the OS assign a free port, then return it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_server(url: str, attempts: int = 10, interval: float = 0.5) -> bool:
    """Poll *url* until it responds or we run out of attempts."""
    for _ in range(attempts):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(interval)
    return False


def main() -> None:
    import os

    import webview

    # Force the Qt xcb (X11) backend on Linux. Without this, Qt tries Wayland
    # first (which may not have a compositor socket) then xcb, and can crash
    # before xcb gets a chance to load properly.
    if os.name != "nt" and "WAYLAND_DISPLAY" not in os.environ:
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    elif "WAYLAND_DISPLAY" in os.environ:
        # Unset WAYLAND_DISPLAY so Qt uses X11 — avoids crash when no Wayland
        # compositor socket is present despite the env var being set.
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    from istadash.main import create_app

    port = _find_free_port()
    flask_app = create_app()

    server_thread = threading.Thread(
        target=lambda: flask_app.run(
            host="127.0.0.1",
            port=port,
            debug=False,
            use_reloader=False,
        ),
        daemon=True,
    )
    server_thread.start()

    url = f"http://127.0.0.1:{port}"
    _wait_for_server(url)

    webview.create_window("IstaDash", url, width=1200, height=800, resizable=True)
    webview.start()


if __name__ == "__main__":
    main()
