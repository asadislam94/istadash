from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from istadash.services.sync import normalise_datetime, normalise_reading
from istadash.storage import Storage


class SyncTests(unittest.TestCase):
    def test_normalise_datetime_converts_to_utc(self) -> None:
        result = normalise_datetime("2026-04-12T14:30:00+01:00")
        self.assertEqual(result, "2026-04-12T13:30:00+00:00")

    def test_insert_readings_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = Storage(Path(tmp_dir) / "meter_reads.db")
            reading = {
                "meter_id": 8340686,
                "meter_no": "Heat-1",
                "read_at": "2026-04-12T13:30:00+00:00",
                "register_name": "Heating",
                "unit_of_measure": "kWh",
                "read_value": 123.0,
                "read_value_text": "123",
                "read_type": "Actual Read",
                "is_estimated": False,
                "is_invoiced": False,
                "source_payload": None,
                "created_at": "2026-04-12T13:31:00+00:00",
            }
            inserted_first = storage.insert_readings([reading])
            inserted_second = storage.insert_readings([reading])
            self.assertEqual(inserted_first, 1)
            self.assertEqual(inserted_second, 0)

    def test_normalise_reading_labels_estimated_invoiced(self) -> None:
        result = normalise_reading(
            {
                "EndReadDate": "2026-04-12T14:30:00+01:00",
                "Register": "Heating",
                "UOM": "kWh",
                "EndRead": "456",
                "EndReadTypes": ["Estimated Read"],
                "Invoiced": True,
            },
            {"MeterID": 8340686, "MeterNo": "Heat-1"},
            created_at="2026-04-12T13:31:00+00:00",
            debug_raw_payloads=False,
        )
        self.assertEqual(result["read_type"], "Estimated Read (Invoiced)")
        self.assertTrue(result["is_estimated"])
        self.assertTrue(result["is_invoiced"])

    def test_query_daily_usage_calculates_differences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = Storage(Path(tmp_dir) / "meter_reads.db")
            rows = [
                {
                    "meter_id": 8340686,
                    "meter_no": "Heat-1",
                    "read_at": "2026-04-10T23:00:00+00:00",
                    "register_name": "01",
                    "unit_of_measure": "kWh",
                    "read_value": 100.0,
                    "read_value_text": "100",
                    "read_type": "Actual Read",
                    "is_estimated": False,
                    "is_invoiced": False,
                    "source_payload": None,
                    "created_at": "2026-04-12T13:31:00+00:00",
                },
                {
                    "meter_id": 8340686,
                    "meter_no": "Heat-1",
                    "read_at": "2026-04-11T23:00:00+00:00",
                    "register_name": "01",
                    "unit_of_measure": "kWh",
                    "read_value": 112.0,
                    "read_value_text": "112",
                    "read_type": "Actual Read",
                    "is_estimated": False,
                    "is_invoiced": False,
                    "source_payload": None,
                    "created_at": "2026-04-12T13:31:00+00:00",
                },
            ]
            storage.insert_readings(rows)
            usage = storage.query_daily_usage(limit=10)
            self.assertEqual(len(usage), 1)
            self.assertEqual(usage[0]["usage_value"], 12.0)
            self.assertEqual(usage[0]["read_value_text"], "112")


if __name__ == "__main__":
    unittest.main()
