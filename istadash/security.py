from __future__ import annotations

import json
import warnings
from pathlib import Path

import keyring
import keyring.errors

SERVICE_NAME = "istadash"
TOKEN_KEY = "ista_session_cookie"

# Fallback token file used when no OS keyring backend is available (e.g.
# headless Linux without a Secret Service daemon).  The file is mode 0600 and
# lives in the same config directory as the rest of the app data.
_FALLBACK_FILE = Path.home() / ".config" / "istadash" / ".session_token"


def _has_keyring() -> bool:
    """Return True if a real OS keyring backend is available at call time."""
    try:
        keyring.get_password(SERVICE_NAME, "__probe__")
        return True
    except (keyring.errors.NoKeyringError, Exception):
        return False


def save_session_cookie(cookie_value: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, TOKEN_KEY, cookie_value)
    except (keyring.errors.NoKeyringError, Exception):
        _fallback_write(cookie_value)


def load_session_cookie() -> str | None:
    try:
        value = keyring.get_password(SERVICE_NAME, TOKEN_KEY)
        if value is not None:
            return value
    except (keyring.errors.NoKeyringError, Exception):
        pass
    return _fallback_read()


def clear_session_cookie() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, TOKEN_KEY)
    except (keyring.errors.NoKeyringError, keyring.errors.PasswordDeleteError, Exception):
        pass
    _fallback_clear()


# ── File-based fallback (headless / no Secret Service) ───────────────────────

def _fallback_write(value: str) -> None:
    warnings.warn(
        "No OS keyring available — session token stored in plain file. "
        "Install a Secret Service daemon (e.g. gnome-keyring) for secure storage.",
        stacklevel=3,
    )
    _FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FALLBACK_FILE.write_text(json.dumps({"token": value}), encoding="utf-8")
    _FALLBACK_FILE.chmod(0o600)


def _fallback_read() -> str | None:
    try:
        data = json.loads(_FALLBACK_FILE.read_text(encoding="utf-8"))
        return data.get("token")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _fallback_clear() -> None:
    try:
        _FALLBACK_FILE.unlink(missing_ok=True)
    except OSError:
        pass

