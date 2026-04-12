from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "istadash"
CONFIG_PATH = Path.home() / ".config" / APP_DIR_NAME / "config.json"
DATA_DIR = Path.home() / ".local" / "share" / APP_DIR_NAME


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    base_url: str
    meter_id: int | None
    property_scope: str | None
    database_path: Path
    export_dir: Path
    flask_secret_key: str
    flask_host: str
    flask_port: int
    flask_debug: bool
    request_timeout_seconds: int
    items_per_page: int
    billable_only: bool
    debug_raw_payloads: bool

    @classmethod
    def from_file(cls) -> "Settings":
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        payload: dict = {}
        if CONFIG_PATH.exists():
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        flask_secret = payload.get("flask_secret_key") or secrets.token_hex(24)
        database_path = Path(payload.get("database_path", DATA_DIR / "meter_reads.db"))
        export_dir = Path(payload.get("export_dir", DATA_DIR / "exports"))

        database_path.parent.mkdir(parents=True, exist_ok=True)
        export_dir.mkdir(parents=True, exist_ok=True)

        settings = cls(
            base_url=str(payload.get("base_url", "https://myista.co.uk")).rstrip("/"),
            meter_id=int(payload["meter_id"]) if payload.get("meter_id") else None,
            property_scope=(str(payload.get("property_scope")) if payload.get("property_scope") else None),
            database_path=database_path,
            export_dir=export_dir,
            flask_secret_key=flask_secret,
            flask_host=str(payload.get("flask_host", "127.0.0.1")),
            flask_port=int(payload.get("flask_port", 8000)),
            flask_debug=_to_bool(str(payload.get("flask_debug", "false")), False),
            request_timeout_seconds=int(payload.get("request_timeout_seconds", 30)),
            items_per_page=int(payload.get("items_per_page", 50)),
            billable_only=_to_bool(str(payload.get("billable_only", "true")), True),
            debug_raw_payloads=_to_bool(str(payload.get("debug_raw_payloads", "false")), False),
        )
        settings.save()
        return settings

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "base_url": self.base_url,
            "meter_id": self.meter_id,
            "property_scope": self.property_scope,
            "database_path": str(self.database_path),
            "export_dir": str(self.export_dir),
            "flask_secret_key": self.flask_secret_key,
            "flask_host": self.flask_host,
            "flask_port": self.flask_port,
            "flask_debug": self.flask_debug,
            "request_timeout_seconds": self.request_timeout_seconds,
            "items_per_page": self.items_per_page,
            "billable_only": self.billable_only,
            "debug_raw_payloads": self.debug_raw_payloads,
        }
        CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def is_onboarded(self) -> bool:
        return self.meter_id is not None and self.property_scope is not None

    def update_selection(self, *, meter_id: int, property_scope: str) -> None:
        self.meter_id = meter_id
        self.property_scope = property_scope
        self.save()
