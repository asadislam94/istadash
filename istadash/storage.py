from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meters (
    meter_id INTEGER PRIMARY KEY,
    meter_no TEXT,
    utility_type TEXT,
    meter_status TEXT,
    last_seen_at TEXT NOT NULL,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id INTEGER NOT NULL,
    meter_no TEXT,
    read_at TEXT NOT NULL,
    register_name TEXT,
    unit_of_measure TEXT,
    read_value REAL,
    read_value_text TEXT NOT NULL,
    read_type TEXT NOT NULL,
    is_estimated INTEGER NOT NULL,
    is_invoiced INTEGER NOT NULL,
    source_payload TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (meter_id, read_at, register_name, read_value_text, read_type, is_invoiced)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    message TEXT,
    selected_meter_id INTEGER,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    export_path TEXT
);
"""


class Storage:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def upsert_meters(self, meters: Iterable[dict], seen_at: str) -> None:
        rows = [
            (
                int(meter["MeterID"]),
                meter.get("MeterNo"),
                meter.get("TypeDescription"),
                meter.get("MeterStatus"),
                seen_at,
                meter.get("raw_json"),
            )
            for meter in meters
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO meters (meter_id, meter_no, utility_type, meter_status, last_seen_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(meter_id) DO UPDATE SET
                    meter_no=excluded.meter_no,
                    utility_type=excluded.utility_type,
                    meter_status=excluded.meter_status,
                    last_seen_at=excluded.last_seen_at,
                    raw_json=excluded.raw_json
                """,
                rows,
            )

    def create_sync_run(self, started_at: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO sync_runs (started_at, status) VALUES (?, ?)",
                (started_at, "running"),
            )
            return int(cursor.lastrowid)

    def finish_sync_run(
        self,
        sync_run_id: int,
        *,
        status: str,
        message: str,
        selected_meter_id: int | None,
        fetched_count: int,
        inserted_count: int,
        export_path: str | None,
        finished_at: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                SET finished_at = ?,
                    status = ?,
                    message = ?,
                    selected_meter_id = ?,
                    fetched_count = ?,
                    inserted_count = ?,
                    export_path = ?
                WHERE id = ?
                """,
                (
                    finished_at,
                    status,
                    message,
                    selected_meter_id,
                    fetched_count,
                    inserted_count,
                    export_path,
                    sync_run_id,
                ),
            )

    def insert_readings(self, readings: Iterable[dict]) -> int:
        rows = [
            (
                reading["meter_id"],
                reading.get("meter_no"),
                reading["read_at"],
                reading.get("register_name"),
                reading.get("unit_of_measure"),
                reading.get("read_value"),
                reading["read_value_text"],
                reading["read_type"],
                1 if reading.get("is_estimated") else 0,
                1 if reading.get("is_invoiced") else 0,
                reading.get("source_payload"),
                reading["created_at"],
            )
            for reading in readings
        ]

        inserted = 0
        with self.connect() as connection:
            for row in rows:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO readings (
                        meter_id,
                        meter_no,
                        read_at,
                        register_name,
                        unit_of_measure,
                        read_value,
                        read_value_text,
                        read_type,
                        is_estimated,
                        is_invoiced,
                        source_payload,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )
                inserted += cursor.rowcount
        return inserted

    def query_readings(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 250,
    ) -> list[sqlite3.Row]:
        clauses = []
        params: list[object] = []
        if date_from:
            clauses.append("date(read_at) >= date(?)")
            params.append(date_from)
        if date_to:
            clauses.append("date(read_at) <= date(?)")
            params.append(date_to)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                SELECT meter_id, meter_no, read_at, register_name, unit_of_measure,
                       read_value, read_value_text, read_type, is_estimated, is_invoiced
                FROM readings
                {where}
                ORDER BY datetime(read_at) DESC
                LIMIT ?
                """,
                params,
            )
            return list(cursor.fetchall())

    def query_daily_usage(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 250,
    ) -> list[sqlite3.Row]:
        clauses = ["previous_value IS NOT NULL"]
        params: list[object] = []
        if date_from:
            clauses.append("date(read_at) >= date(?)")
            params.append(date_from)
        if date_to:
            clauses.append("date(read_at) <= date(?)")
            params.append(date_to)

        where = f"WHERE {' AND '.join(clauses)}"
        params.append(limit)

        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                WITH usage_reads AS (
                    SELECT
                        meter_id,
                        meter_no,
                        read_at,
                        register_name,
                        unit_of_measure,
                        read_value,
                        read_value_text,
                        read_type,
                        is_estimated,
                        is_invoiced,
                        LAG(read_value) OVER (
                            PARTITION BY meter_id, COALESCE(register_name, '')
                            ORDER BY datetime(read_at)
                        ) AS previous_value
                    FROM readings
                )
                SELECT
                    meter_id,
                    meter_no,
                    read_at,
                    register_name,
                    unit_of_measure,
                    read_value,
                    read_value_text,
                    read_type,
                    is_estimated,
                    is_invoiced,
                    ROUND(read_value - previous_value, 3) AS usage_value
                FROM usage_reads
                {where}
                ORDER BY datetime(read_at) DESC
                LIMIT ?
                """,
                params,
            )
            return list(cursor.fetchall())

    def get_summary(self) -> sqlite3.Row:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                WITH usage_reads AS (
                    SELECT
                        meter_id,
                        read_at,
                        read_value,
                        read_value_text,
                        unit_of_measure,
                        LAG(read_value) OVER (
                            PARTITION BY meter_id, COALESCE(register_name, '')
                            ORDER BY datetime(read_at)
                        ) AS previous_value
                    FROM readings
                ),
                latest_read AS (
                    SELECT read_at, read_value_text
                    FROM readings
                    ORDER BY datetime(read_at) DESC
                    LIMIT 1
                ),
                latest_usage AS (
                    SELECT
                        ROUND(read_value - previous_value, 3) AS usage_value,
                        unit_of_measure
                    FROM usage_reads
                    WHERE previous_value IS NOT NULL
                    ORDER BY datetime(read_at) DESC
                    LIMIT 1
                )
                SELECT
                    (SELECT COUNT(*) FROM readings) AS reading_count,
                    (SELECT COUNT(DISTINCT meter_id) FROM readings) AS meter_count,
                    (SELECT read_at FROM latest_read) AS latest_read_at,
                    (SELECT read_value_text FROM latest_read) AS latest_read_value,
                    (SELECT usage_value FROM latest_usage) AS latest_usage_value,
                    (SELECT unit_of_measure FROM latest_usage) AS usage_unit
                """
            )
            return cursor.fetchone()

    def get_chart_points(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                WITH usage_reads AS (
                    SELECT
                        date(read_at) AS read_day,
                        unit_of_measure,
                        read_value,
                        LAG(read_value) OVER (
                            PARTITION BY meter_id, COALESCE(register_name, '')
                            ORDER BY datetime(read_at)
                        ) AS previous_value
                    FROM readings
                )
                SELECT
                    read_day,
                    ROUND(SUM(read_value - previous_value), 3) AS usage_value,
                    MAX(unit_of_measure) AS unit_of_measure
                FROM usage_reads
                WHERE previous_value IS NOT NULL
                GROUP BY read_day
                ORDER BY read_day ASC
                """
            )
            return list(cursor.fetchall())

    def list_sync_runs(self, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                SELECT id, started_at, finished_at, status, message, selected_meter_id,
                       fetched_count, inserted_count, export_path
                FROM sync_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return list(cursor.fetchall())

    def export_readings_csv(
        self,
        destination: Path,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        clauses: list[str] = []
        params: list[object] = []
        if start_date:
            clauses.append("date(read_at) >= date(?)")
            params.append(start_date)
        if end_date:
            clauses.append("date(read_at) <= date(?)")
            params.append(end_date)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                SELECT meter_id, meter_no, read_at, register_name, unit_of_measure,
                       read_value, read_value_text, read_type, is_estimated, is_invoiced
                FROM readings
                {where}
                ORDER BY datetime(read_at) DESC
                """,
                params,
            )
            rows = cursor.fetchall()

        with destination.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "meter_id",
                    "meter_no",
                    "read_at",
                    "register_name",
                    "unit_of_measure",
                    "read_value",
                    "read_value_text",
                    "read_type",
                    "is_estimated",
                    "is_invoiced",
                ]
            )
            for row in rows:
                writer.writerow([row[key] for key in row.keys()])

        return destination
