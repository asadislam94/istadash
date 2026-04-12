from __future__ import annotations

import keyring

SERVICE_NAME = "istadash"
TOKEN_KEY = "ista_session_cookie"


def save_session_cookie(cookie_value: str) -> None:
    keyring.set_password(SERVICE_NAME, TOKEN_KEY, cookie_value)


def load_session_cookie() -> str | None:
    return keyring.get_password(SERVICE_NAME, TOKEN_KEY)


def clear_session_cookie() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, TOKEN_KEY)
    except keyring.errors.PasswordDeleteError:
        return
