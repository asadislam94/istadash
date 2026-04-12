from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from istadash.storage import Storage


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self._tmp.name) / "test.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _reading(self, **overrides: object) -> dict:
        base: dict = {
            "meter_id": 1,
            "meter_no": "M-1",
            "read_at": "2026-01-01T00:00:00+00:00",
            "register_name": "Heat",
            "unit_of_measure": "kWh",
            "read_value": 100.0,
            "read_value_text": "100",
            "read_type": "Actual Read",
            "is_estimated": False,
            "is_invoiced": False,
            "source_payload": None,
            "created_at": "2026-01-01T00:00:01+00:00",
        }
        base.update(overrides)
        return base

    def test_insert_readings_inserts_one(self) -> None:
        count = self.storage.insert_readings([self._reading()])
        self.assertEqual(count, 1)

    def test_insert_readings_deduplicates(self) -> None:
        reading = self._reading()
        self.storage.insert_readings([reading])
        second = self.storage.insert_readings([reading])
        self.assertEqual(second, 0)

    def test_upsert_meters_is_idempotent(self) -> None:
        meter = {
            "MeterID": 42,
            "MeterNo": "H-42",
            "TypeDescription": "Heat",
            "MeterStatus": "Active",
            "raw_json": None,
        }
        # Must not raise on double-upsert
        self.storage.upsert_meters([meter], seen_at="2026-01-01T00:00:00+00:00")
        self.storage.upsert_meters([meter], seen_at="2026-01-02T00:00:00+00:00")

    def test_query_daily_usage_calculates_delta(self) -> None:
        self.storage.insert_readings([
            self._reading(read_at="2026-01-01T00:00:00+00:00", read_value=100.0, read_value_text="100"),
            self._reading(read_at="2026-01-02T00:00:00+00:00", read_value=112.0, read_value_text="112"),
        ])
        rows = self.storage.query_daily_usage()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["usage_value"], 12.0)

    def test_get_summary_empty_db(self) -> None:
        summary = self.storage.get_summary()
        self.assertEqual(summary["reading_count"], 0)
        self.assertEqual(summary["meter_count"], 0)
        self.assertIsNone(summary["latest_usage_value"])

    def test_get_summary_with_data(self) -> None:
        self.storage.insert_readings([
            self._reading(read_at="2026-01-01T00:00:00+00:00", read_value=100.0, read_value_text="100"),
            self._reading(read_at="2026-01-02T00:00:00+00:00", read_value=115.0, read_value_text="115"),
        ])
        summary = self.storage.get_summary()
        self.assertEqual(summary["reading_count"], 2)
        self.assertAlmostEqual(summary["latest_usage_value"], 15.0)

    def test_get_chart_points(self) -> None:
        self.storage.insert_readings([
            self._reading(read_at="2026-01-01T00:00:00+00:00", read_value=100.0, read_value_text="100"),
            self._reading(read_at="2026-01-02T00:00:00+00:00", read_value=110.0, read_value_text="110"),
        ])
        points = self.storage.get_chart_points()
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0]["usage_value"], 10.0)
