from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from istadash.config import Settings
from istadash.ista_client import IstaClient
from istadash.storage import Storage

log = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalise_datetime(value: str | None) -> str:
    if not value:
        return utc_now_iso()
    cleaned = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return value
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat()


def normalise_meter(meter: dict[str, Any], *, debug_raw_payloads: bool) -> dict[str, Any]:
    result = dict(meter)
    result["raw_json"] = json.dumps(meter, sort_keys=True) if debug_raw_payloads else None
    return result


def normalise_reading(raw: dict[str, Any], meter: dict[str, Any], *, created_at: str, debug_raw_payloads: bool) -> dict[str, Any]:
    read_types = raw.get("EndReadTypes") or []
    estimated = "Estimated Read" in read_types
    read_type = "Estimated Read" if estimated else "Actual Read"
    if raw.get("Invoiced"):
        read_type = f"{read_type} (Invoiced)"

    read_value_text = str(raw.get("EndRead", "")).strip()
    try:
        read_value = float(read_value_text)
    except ValueError:
        read_value = None

    return {
        "meter_id": int(meter["MeterID"]),
        "meter_no": meter.get("MeterNo"),
        "read_at": normalise_datetime(raw.get("EndReadDate")),
        "register_name": raw.get("Register"),
        "unit_of_measure": raw.get("UOM"),
        "read_value": read_value,
        "read_value_text": read_value_text,
        "read_type": read_type,
        "is_estimated": estimated,
        "is_invoiced": bool(raw.get("Invoiced")),
        "source_payload": json.dumps(raw, sort_keys=True) if debug_raw_payloads else None,
        "created_at": created_at,
    }


@dataclass(slots=True)
class SyncReport:
    selected_meter_id: int
    selected_meter_no: str | None
    selected_utility: str | None
    fetched_count: int
    inserted_count: int
    export_path: Path
    property_scope: str | None


def run_sync(settings: Settings, storage: Storage, *, session_cookie: str) -> SyncReport:
    started_at = utc_now_iso()
    sync_run_id = storage.create_sync_run(started_at)
    log.info("run_sync: started (run #%d, meter_id=%s)", sync_run_id, settings.meter_id)

    selected_meter = None
    fetched_count = 0
    inserted_count = 0
    export_path: Path | None = None

    try:
        client = IstaClient(settings, session_cookie=session_cookie)
        meters = [normalise_meter(meter, debug_raw_payloads=settings.debug_raw_payloads) for meter in client.get_meters()]
        log.debug("run_sync: got %d meters from API", len(meters))
        storage.upsert_meters(meters, seen_at=started_at)

        selected_meter = client.select_meter(meters)
        log.info("run_sync: selected meter %s (%s)", selected_meter.get("MeterID"), selected_meter.get("TypeDescription"))

        raw_reads = client.fetch_meter_reads(int(selected_meter["MeterID"]))
        fetched_count = len(raw_reads)
        log.info("run_sync: fetched %d raw reads from API", fetched_count)

        readings = [
            normalise_reading(
                raw,
                selected_meter,
                created_at=started_at,
                debug_raw_payloads=settings.debug_raw_payloads,
            )
            for raw in raw_reads
        ]
        inserted_count = storage.insert_readings(readings)
        log.info("run_sync: inserted %d new readings", inserted_count)

        export_path = storage.export_readings_csv(settings.export_dir / "readings.csv")
        log.debug("run_sync: exported CSV to %s", export_path)
        storage.finish_sync_run(
            sync_run_id,
            status="success",
            message=f"Fetched {fetched_count} reads, inserted {inserted_count} new rows",
            selected_meter_id=int(selected_meter["MeterID"]),
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            export_path=str(export_path),
            finished_at=utc_now_iso(),
        )
        return SyncReport(
            selected_meter_id=int(selected_meter["MeterID"]),
            selected_meter_no=selected_meter.get("MeterNo"),
            selected_utility=selected_meter.get("TypeDescription"),
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            export_path=export_path,
            property_scope=settings.property_scope,
        )
    except Exception as exc:
        log.exception("run_sync: failed on run #%d — %s", sync_run_id, exc)
        storage.finish_sync_run(
            sync_run_id,
            status="failed",
            message=str(exc),
            selected_meter_id=None if selected_meter is None else int(selected_meter["MeterID"]),
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            export_path=None if export_path is None else str(export_path),
            finished_at=utc_now_iso(),
        )
        raise
