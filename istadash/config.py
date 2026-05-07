from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "istadash"

log = logging.getLogger(__name__)


def _get_config_dir() -> Path:
    """Return the platform-appropriate directory for configuration files."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if not base:
            raise RuntimeError("%APPDATA% is not set")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    # Linux / XDG
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / APP_DIR_NAME


def _get_data_dir() -> Path:
    """Return the platform-appropriate directory for application data."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if not base:
            raise RuntimeError("%LOCALAPPDATA% is not set")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    # Linux / XDG
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_DIR_NAME


CONFIG_DIR: Path = _get_config_dir()
DATA_DIR: Path = _get_data_dir()
CONFIG_PATH: Path = CONFIG_DIR / "config.json"


def _migrate_legacy_paths() -> None:
    """Copy files from the old hardcoded XDG-style paths to the current
    platform-correct directories, then delete the vacated source trees.

    The previous code always used ``~/.config/istadash`` (config) and
    ``~/.local/share/istadash`` (data) regardless of platform.  On Linux
    those paths are still correct, so this function is a no-op there.
    On macOS and Windows the data must move to the proper OS location.

    Rules:
    - Files are only copied if they do *not* already exist at the destination
      (so a partially-migrated state is safe to re-run).
    - After copying, the old ``APP_DIR_NAME`` directory is removed entirely.
    """
    # Old paths were always these, regardless of platform.
    old_config_dir = Path.home() / ".config" / APP_DIR_NAME
    old_data_dir = Path.home() / ".local" / "share" / APP_DIR_NAME

    migrations: list[tuple[Path, Path]] = []

    for old_dir, new_dir in (
        (old_config_dir, CONFIG_DIR),
        (old_data_dir, DATA_DIR),
    ):
        # Skip if the source is missing or is identical to the destination.
        if old_dir.resolve() == new_dir.resolve():
            continue
        if not old_dir.exists():
            continue
        migrations.append((old_dir, new_dir))

    if not migrations:
        return

    for old_dir, new_dir in migrations:
        log.info("migrate_legacy_paths: %s → %s", old_dir, new_dir)
        new_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        for src in old_dir.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(old_dir)
            dst = new_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                log.debug("migrate_legacy_paths: skip (already exists) %s", dst)
            else:
                shutil.copy2(src, dst)
                log.debug("migrate_legacy_paths: copied %s", rel)
                copied += 1

        # Always remove the old APP_DIR_NAME directory — even if it was empty.
        shutil.rmtree(old_dir)
        log.info("migrate_legacy_paths: removed %s (%d file(s) migrated)", old_dir, copied)


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
        _migrate_legacy_paths()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        payload: dict = {}
        if CONFIG_PATH.exists():
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        flask_secret = payload.get("flask_secret_key") or secrets.token_hex(24)
        database_path = DATA_DIR / "meter_reads.db"
        export_dir = DATA_DIR / "exports"

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
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "base_url": self.base_url,
            "meter_id": self.meter_id,
            "property_scope": self.property_scope,
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
