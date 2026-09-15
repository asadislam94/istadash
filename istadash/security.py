from __future__ import annotations

import json
import logging
import warnings

from istadash.config import CONFIG_DIR

# ── Conditional import ───────────────────────────────────────────────────────
try:
    import keyring
    import keyring.errors
    _HAS_KEYRING_MODULE = True
except ImportError:
    keyring = None  # type: ignore[assignment]
    _HAS_KEYRING_MODULE = False

SERVICE_NAME = "istadash"
TOKEN_KEY = "ista_session_cookie"
CREDENTIALS_USERNAME_KEY = "ista_credentials_username"
CREDENTIALS_PASSWORD_KEY = "ista_credentials_password"

# Fallback token file used when no OS keyring backend is available (e.g.
# headless Linux without a Secret Service daemon).  The file is mode 0600 and
# lives in the same config directory as the rest of the app data.
_FALLBACK_FILE = CONFIG_DIR / ".session_token"

log = logging.getLogger(__name__)


# ── Internal helpers (ONLY place that touches keyring.*) ─────────────────────
def _keyring_get(key: str) -> str | None:
    if not _HAS_KEYRING_MODULE:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, key)
    except Exception:
        return None

def _keyring_set(key: str, value: str) -> bool:
    if not _HAS_KEYRING_MODULE:
        return False
    try:
        keyring.set_password(SERVICE_NAME, key, value)
        return True
    except Exception:
        return False

def _keyring_delete(key: str) -> None:
    if not _HAS_KEYRING_MODULE:
        return
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except Exception:
        pass


def _has_keyring() -> bool:
    """Return True if a real OS keyring backend is available at call time."""
    if not _HAS_KEYRING_MODULE:
        return False
    try:
        keyring.get_password(SERVICE_NAME, "__probe__")
        log.debug("_has_keyring: OS keyring is available")
        return True
    except Exception as exc:
        log.debug("_has_keyring: no OS keyring — %s", exc)
        return False


def save_session_cookie(cookie_value: str) -> None:
    if _keyring_set(TOKEN_KEY, cookie_value):
        log.info("save_session_cookie: saved to OS keyring")
    else:
        log.warning("save_session_cookie: keyring unavailable, using fallback file")
        _fallback_write(cookie_value)


def load_session_cookie() -> str | None:
    value = _keyring_get(TOKEN_KEY)
    if value is not None:
        log.debug("load_session_cookie: loaded from OS keyring")
        return value
        
    log.debug("load_session_cookie: OS keyring unavailable, trying fallback")
    result = _fallback_read()
    if result:
        log.debug("load_session_cookie: loaded from fallback file")
    else:
        log.debug("load_session_cookie: no token found anywhere")
    return result


def clear_session_cookie() -> None:
    _keyring_delete(TOKEN_KEY)
    log.info("clear_session_cookie: removed from OS keyring (if present)")
    _fallback_clear()


# ── File-based fallback (headless / no Secret Service) ───────────────────────

def save_credentials(username: str, password: str) -> bool:
    """Save username and password to the OS keyring.

    Returns True on success.  Returns False (without raising) when no keyring
    backend is available — callers should not store credentials in that case.
    """
    if not _has_keyring():
        log.warning("save_credentials: no OS keyring available — credentials NOT saved")
        return False
    
    ok1 = _keyring_set(CREDENTIALS_USERNAME_KEY, username)
    ok2 = _keyring_set(CREDENTIALS_PASSWORD_KEY, password)
    
    if ok1 and ok2:
        log.info("save_credentials: credentials saved to OS keyring")
        return True
    else:
        log.warning("save_credentials: failed to save credentials")
        return False


def load_credentials() -> tuple[str, str] | None:
    """Return (username, password) from the OS keyring, or None if not stored."""
    username = _keyring_get(CREDENTIALS_USERNAME_KEY)
    password = _keyring_get(CREDENTIALS_PASSWORD_KEY)
    if username and password:
        log.debug("load_credentials: loaded from OS keyring")
        return username, password
    
    log.debug("load_credentials: keyring unavailable or no credentials stored")
    return None


def clear_credentials() -> None:
    """Remove saved credentials from the OS keyring."""
    _keyring_delete(CREDENTIALS_USERNAME_KEY)
    _keyring_delete(CREDENTIALS_PASSWORD_KEY)
    log.info("clear_credentials: removed credentials from OS keyring (if present)")


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
