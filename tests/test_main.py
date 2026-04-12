from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class MainRouteTests(unittest.TestCase):
    """Smoke tests for Flask route layer."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        config_path = tmp_path / "config.json"
        data_dir = tmp_path / "data"

        # Isolate Settings to temp dir so tests never touch the real config
        self._patches = [
            mock.patch("istadash.config.CONFIG_PATH", config_path),
            mock.patch("istadash.config.DATA_DIR", data_dir),
            # Prevent keyring lookups in environments without a secret service
            mock.patch("istadash.main.load_session_cookie", return_value=None),
        ]
        for p in self._patches:
            p.start()

        from istadash.main import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        self.client = flask_app.test_client()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_login_get_returns_200(self) -> None:
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"IstaDash", response.data)

    def test_root_without_session_redirects_to_login(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"/login", response.data)


class DesktopEntryPointTests(unittest.TestCase):
    """Ensure the PyWebView entry point can be imported and is runnable."""

    def test_webview_importable(self) -> None:
        """pywebview must be installed and its Qt platform backend must load.

        Missing pywebview[qt] or its system libs causes exit code 247/250 at launch.
        On Ubuntu, install: libnspr4 libnss3 libgbm1 libasound2t64 libxkbfile1
                            libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1
                            libxcb-shape0 libxcb-xkb1 libxkbcommon-x11-0
        """
        try:
            import webview  # noqa: F401
        except ImportError as exc:
            self.fail(f"'import webview' failed — install pywebview[qt]: {exc}")

        # Also verify the Qt platform module loads — this is the real failure
        # point when system xcb/nspr/alsa libs are missing.
        try:
            import webview.platforms.qt  # noqa: F401
        except ImportError as exc:
            self.fail(
                f"PyWebView Qt backend failed — on Ubuntu run: sudo apt install "
                f"libnspr4 libnss3 libgbm1 libasound2t64 libxkbfile1 libxcb-cursor0 "
                f"libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 libxkbcommon-x11-0. "
                f"Error: {exc}"
            )

    def test_main_function_exists(self) -> None:
        """istadash.__main__ must expose a callable main()."""
        import istadash.__main__ as entry

        self.assertTrue(
            callable(getattr(entry, "main", None)),
            "__main__.main is not callable",
        )

    def test_find_free_port_returns_valid_port(self) -> None:
        """_find_free_port() must return a port in the valid range."""
        from istadash.__main__ import _find_free_port

        port = _find_free_port()
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        self.assertLessEqual(port, 65535)
