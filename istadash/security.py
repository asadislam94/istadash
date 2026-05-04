from __future__ import annotations

import json
import logging
import warnings

import keyring
import keyring.errors

from istadash.config import CONFIG_DIR

SERVICE_NAME = "istadash"
TOKEN_KEY = "ista_session_cookie"

# Fallback token file used when no OS keyring backend is available (e.g.
# headless Linux without a Secret Service daemon).  The file is mode 0600 and
# lives in the same config directory as the rest of the app data.
_FALLBACK_FILE = CONFIG_DIR / ".session_token"

log = logging.getLogger(__name__)


def _has_keyring() -> bool:
    """Return True if a real OS keyring backend is available at call time."""
    try:
        keyring.get_password(SERVICE_NAME, "__probe__")
        log.debug("_has_keyring: OS keyring is available")
        return True
    except (keyring.errors.NoKeyringError, Exception) as exc:
        log.debug("_has_keyring: no OS keyring — %s", exc)
        return False


def save_session_cookie(cookie_value: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, TOKEN_KEY, cookie_value)
        log.info("save_session_cookie: saved to OS keyring")
    except (keyring.errors.NoKeyringError, Exception) as exc:
        log.warning("save_session_cookie: keyring unavailable (%s), using fallback file", exc)
        _fallback_write(cookie_value)


def load_session_cookie() -> str | None:
    try:
        value = keyring.get_password(SERVICE_NAME, TOKEN_KEY)
        if value is not None:
            log.debug("load_session_cookie: loaded from OS keyring")
            return value
    except (keyring.errors.NoKeyringError, Exception) as exc:
        log.debug("load_session_cookie: keyring unavailable (%s), trying fallback", exc)
    result = _fallback_read()
    if result:
        log.debug("load_session_cookie: loaded from fallback file")
    else:
        log.debug("load_session_cookie: no token found anywhere")
    return result


def clear_session_cookie() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, TOKEN_KEY)
        log.info("clear_session_cookie: removed from OS keyring")
    except (keyring.errors.NoKeyringError, keyring.errors.PasswordDeleteError, Exception) as exc:
        log.debug("clear_session_cookie: keyring removal skipped — %s", exc)
    _fallback_clear()


# ── File-based fallback (headless / no Secret Service) ───────────────────────

def _fallback_write(value: str) -> None:
    warnings.warn(
        "No OS keyring available — session token stored in plain file. "
        "Install a Secret Service daemon (e.g. gnome-keyring) for secure storage.",
        stacklevel=3,
    )
    log.warning("_fallback_write: writing token to %s (mode 0600)", _FALLBACK_FILE)
    _FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FALLBACK_FILE.write_text(json.dumps({"token": value}), encoding="utf-8")
    _FALLBACK_FILE.chmod(0o600)


def _fallback_read() -> str | None:
    try:
        data = json.loads(_FALLBACK_FILE.read_text(encoding="utf-8"))
        log.debug("_fallback_read: read token from %s", _FALLBACK_FILE)
        return data.get("token")
    except FileNotFoundError:
        log.debug("_fallback_read: fallback file does not exist")
        return None
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("_fallback_read: failed to read fallback file — %s", exc)
        return None


def _fallback_clear() -> None:
    try:
        _FALLBACK_FILE.unlink(missing_ok=True)
        log.debug("_fallback_clear: removed fallback file")
    except OSError as exc:
        log.warning("_fallback_clear: could not remove fallback file — %s", exc)

