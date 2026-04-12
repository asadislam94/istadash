from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class ConfigTests(unittest.TestCase):
    """Tests for istadash.config.Settings."""

    def _settings_from(self, tmp_path: Path, payload: dict | None = None):
        """Create a Settings instance isolated to *tmp_path*."""
        config_path = tmp_path / "config.json"
        data_dir = tmp_path / "data"
        if payload is not None:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(payload), encoding="utf-8")
        with (
            mock.patch("istadash.config.CONFIG_PATH", config_path),
            mock.patch("istadash.config.DATA_DIR", data_dir),
        ):
            import istadash.config
            return istadash.config.Settings.from_file()

    def test_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings_from(Path(tmp))
            self.assertEqual(settings.flask_host, "127.0.0.1")
            self.assertEqual(settings.flask_port, 8000)
            self.assertIsNone(settings.meter_id)
            self.assertIsNone(settings.property_scope)

    def test_is_onboarded_false_without_meter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings_from(Path(tmp))
            self.assertFalse(settings.is_onboarded())

    def test_is_onboarded_true_with_meter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = self._settings_from(
                Path(tmp), {"meter_id": 42, "property_scope": "CUST-1"}
            )
            self.assertTrue(settings.is_onboarded())

    def test_update_selection_persists_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.json"
            data_dir = tmp_path / "data"
            with (
                mock.patch("istadash.config.CONFIG_PATH", config_path),
                mock.patch("istadash.config.DATA_DIR", data_dir),
            ):
                import istadash.config
                settings = istadash.config.Settings.from_file()
                settings.update_selection(meter_id=99, property_scope="CUST-99")

            self.assertEqual(settings.meter_id, 99)
            saved = json.loads(config_path.read_text())
            self.assertEqual(saved["meter_id"], 99)
            self.assertEqual(saved["property_scope"], "CUST-99")
