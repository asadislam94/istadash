from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse


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
        self.app = flask_app
        self.client = flask_app.test_client()

        from istadash.main import _sync_state

        _sync_state.update(
            {
                "status": "idle",
                "message": "",
                "started_at": None,
                "result": None,
            }
        )

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

    def test_api_sync_status_idle(self) -> None:
        response = self.client.get("/api/sync-status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsNotNone(data)
        self.assertEqual(data.get("status"), "idle")

    def test_parse_date_valid(self) -> None:
        from istadash.main import _parse_date

        self.assertEqual(_parse_date("2026-01-15"), "2026-01-15")
        self.assertIsNone(_parse_date(None))
        self.assertIsNone(_parse_date(""))

    def test_parse_date_rejects_invalid(self) -> None:
        from istadash.main import _parse_date

        self.assertIsNone(_parse_date("15-01-2026"))
        self.assertIsNone(_parse_date("2026/01/15"))
        self.assertIsNone(_parse_date("not-a-date"))
        self.assertIsNone(_parse_date("'; DROP TABLE readings; --"))

    def test_login_page_shows_save_credentials_checkbox_when_keyring_available(self) -> None:
        with mock.patch("istadash.security._has_keyring", return_value=True):
            response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"name=\"save_credentials\"", response.data)

    def test_login_page_hides_save_credentials_checkbox_when_keyring_unavailable(self) -> None:
        with mock.patch("istadash.security._has_keyring", return_value=False):
            response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"name=\"save_credentials\"", response.data)

    def test_full_login_flow_saves_credentials_when_selected(self) -> None:
        ista_client = mock.Mock()
        ista_client.login_with_credentials.return_value = True
        ista_client.get_properties.return_value = [{"CustId": "P-1", "Active": True, "AddressLine1": "One St"}]
        ista_client.get_meters.return_value = [
            {"MeterID": 101, "MeterStatus": "Active", "TypeDescription": "Gas", "MeterNo": "G-1"}
        ]
        ista_client.get_session_cookie.return_value = "cookie-abc"

        report = SimpleNamespace(
            selected_meter_id=101,
            selected_utility="Gas",
            fetched_count=5,
            inserted_count=2,
        )

        with (
            mock.patch("istadash.main.IstaClient", return_value=ista_client),
            mock.patch("istadash.main.save_session_cookie") as save_cookie,
            mock.patch("istadash.main.save_credentials") as save_creds,
            mock.patch("istadash.main.run_sync", return_value=report),
        ):
            start = self.client.post(
                "/login/start",
                data={
                    "username": "user@example.com",
                    "password": "pw",
                    "save_credentials": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(start.status_code, 302)
            self.assertIn("/login/meter", start.headers["Location"])

            meter = self.client.get(start.headers["Location"], follow_redirects=False)
            self.assertEqual(meter.status_code, 302)
            self.assertIn("/login/complete", meter.headers["Location"])

            complete = self.client.get(meter.headers["Location"], follow_redirects=False)
            self.assertEqual(complete.status_code, 302)
            self.assertEqual(urlparse(complete.headers["Location"]).path, "/")

        save_cookie.assert_called_once_with("cookie-abc")
        save_creds.assert_called_once_with("user@example.com", "pw")

    def test_full_login_flow_does_not_save_credentials_when_unchecked(self) -> None:
        ista_client = mock.Mock()
        ista_client.login_with_credentials.return_value = True
        ista_client.get_properties.return_value = [{"CustId": "P-2", "Active": True, "AddressLine1": "Two St"}]
        ista_client.get_meters.return_value = [
            {"MeterID": 202, "MeterStatus": "Active", "TypeDescription": "Heat", "MeterNo": "H-2"}
        ]
        ista_client.get_session_cookie.return_value = "cookie-def"

        report = SimpleNamespace(
            selected_meter_id=202,
            selected_utility="Heat",
            fetched_count=7,
            inserted_count=4,
        )

        with (
            mock.patch("istadash.main.IstaClient", return_value=ista_client),
            mock.patch("istadash.main.save_session_cookie") as save_cookie,
            mock.patch("istadash.main.save_credentials") as save_creds,
            mock.patch("istadash.main.run_sync", return_value=report),
        ):
            start = self.client.post(
                "/login/start",
                data={
                    "username": "user2@example.com",
                    "password": "pw2",
                },
                follow_redirects=False,
            )
            self.assertEqual(start.status_code, 302)
            self.assertIn("/login/meter", start.headers["Location"])

            meter = self.client.get(start.headers["Location"], follow_redirects=False)
            self.assertEqual(meter.status_code, 302)
            self.assertIn("/login/complete", meter.headers["Location"])

            complete = self.client.get(meter.headers["Location"], follow_redirects=False)
            self.assertEqual(complete.status_code, 302)
            self.assertEqual(urlparse(complete.headers["Location"]).path, "/")

        save_cookie.assert_called_once_with("cookie-def")
        save_creds.assert_not_called()

    def test_refresh_auth_expired_auto_relogins_and_finishes(self) -> None:
        from istadash.ista_client import AuthorizationExpiredError

        self.app.config["SETTINGS"].update_selection(meter_id=101, property_scope="P-1")

        first_report = AuthorizationExpiredError("expired")
        second_report = SimpleNamespace(
            selected_meter_id=101,
            selected_utility="Gas",
            fetched_count=8,
            inserted_count=3,
        )

        ista_client = mock.Mock()
        ista_client.login_with_credentials.return_value = True
        ista_client.get_session_cookie.return_value = "renewed-cookie"

        class ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                if self._target:
                    self._target()

        with (
            mock.patch("istadash.main.load_session_cookie", return_value="stale-cookie"),
            mock.patch("istadash.main.load_credentials", return_value=("u", "p")),
            mock.patch("istadash.main.IstaClient", return_value=ista_client),
            mock.patch("istadash.main.save_session_cookie") as save_cookie,
            mock.patch("istadash.main.run_sync", side_effect=[first_report, second_report]),
            mock.patch("istadash.main.threading.Thread", ImmediateThread),
        ):
            response = self.client.post("/refresh")
            self.assertEqual(response.status_code, 202)

            status_response = self.client.get("/api/sync-status")
            status_data = status_response.get_json() or {}
            self.assertEqual(status_data.get("status"), "done")
            self.assertIn("Session renewed automatically", status_data.get("message", ""))

        save_cookie.assert_called_once_with("renewed-cookie")

    def test_refresh_auth_expired_without_saved_credentials_requires_login(self) -> None:
        from istadash.ista_client import AuthorizationExpiredError

        self.app.config["SETTINGS"].update_selection(meter_id=101, property_scope="P-1")

        class ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                if self._target:
                    self._target()

        with (
            mock.patch("istadash.main.load_session_cookie", return_value="stale-cookie"),
            mock.patch("istadash.main.load_credentials", return_value=None),
            mock.patch("istadash.main.run_sync", side_effect=AuthorizationExpiredError("expired")),
            mock.patch("istadash.main.clear_session_cookie") as clear_cookie,
            mock.patch("istadash.main.threading.Thread", ImmediateThread),
        ):
            response = self.client.post("/refresh")
            self.assertEqual(response.status_code, 202)

            status_response = self.client.get("/api/sync-status")
            status_data = status_response.get_json() or {}
            self.assertEqual(status_data.get("status"), "auth_expired")

        clear_cookie.assert_called_once()

    def test_login_start_redirects_to_property_selection_with_multiple_properties(self) -> None:
        ista_client = mock.Mock()
        ista_client.login_with_credentials.return_value = True
        ista_client.get_properties.return_value = [
            {"CustId": "P-1", "Active": True, "AddressLine1": "One St"},
            {"CustId": "P-2", "Active": True, "AddressLine1": "Two St"},
        ]
        ista_client.get_session_cookie.return_value = "cookie-multi"

        with mock.patch("istadash.main.IstaClient", return_value=ista_client):
            response = self.client.post(
                "/login/start",
                data={"username": "multi@example.com", "password": "pw"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Select property", response.data)

    def test_login_select_meter_requires_property_scope(self) -> None:
        ista_client = mock.Mock()
        ista_client.login_with_credentials.return_value = True
        ista_client.get_properties.return_value = [{"CustId": "P-1", "Active": True, "AddressLine1": "One St"}]
        ista_client.get_session_cookie.return_value = "cookie-xyz"

        with mock.patch("istadash.main.IstaClient", return_value=ista_client):
            start = self.client.post(
                "/login/start",
                data={"username": "user@example.com", "password": "pw"},
                follow_redirects=False,
            )
            self.assertEqual(start.status_code, 302)

        query = parse_qs(urlparse(start.headers["Location"]).query)
        login_id = query["login_id"][0]
        response = self.client.get(f"/login/meter?login_id={login_id}", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response.headers["Location"]).path, "/login")


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
            import webview
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
