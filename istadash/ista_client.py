from __future__ import annotations

import json
import logging
from typing import Any

import requests
from bs4 import BeautifulSoup

from istadash.config import Settings

log = logging.getLogger(__name__)


class IstaError(RuntimeError):
    pass


class AuthenticationError(IstaError):
    pass


class ConfigurationError(IstaError):
    pass


class AuthorizationExpiredError(AuthenticationError):
    pass


class IstaClient:
    SESSION_COOKIE_NAME = "my-ista-portal-session"

    def __init__(self, settings: Settings, *, session_cookie: str | None = None):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": settings.base_url,
                "Referer": f"{settings.base_url}/auth/login",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self.session.cookies.set("locale", "en")
        self.session.cookies.set("cookie_pref_necessary", "1")
        self.session.cookies.set("cookie_pref_functionality", "1")
        self.session.cookies.set("cookie_pref_analytical", "1")

        if session_cookie:
            self.session.cookies.set(self.SESSION_COOKIE_NAME, session_cookie, domain="myista.co.uk")

    def login_with_credentials(self, *, username: str, password: str, scope: str | None = None) -> bool:
        log.debug("login_with_credentials: fetching login page")
        response = self.session.get(
            f"{self.settings.base_url}/auth/login",
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()

        self._discover_hidden_inputs(response.text)

        payload: dict[str, Any] = {"username": username, "password": password}
        if scope:
            payload["scope"] = scope

        log.debug("login_with_credentials: posting credentials (scope=%s)", scope)
        if not self._post_login_token(payload):
            log.warning("login_with_credentials: server returned false — credentials rejected")
            raise AuthenticationError("ista login was rejected")
        log.info("login_with_credentials: succeeded (scope=%s)", scope)
        return True

    def switch_scope(self, scope: str) -> bool:
        """Switch the active property scope using the existing session cookie.

        Posts only the scope parameter to /auth/loginToken — no credentials needed
        when the session is already authenticated.  Returns True on success.
        Raises AuthorizationExpiredError if the session has expired.
        """
        log.debug("switch_scope: switching to scope=%s", scope)
        if not self._post_login_token({"scope": scope}):
            log.warning("switch_scope: server rejected scope=%s", scope)
            raise AuthorizationExpiredError("scope switch rejected — session may have expired")
        log.info("switch_scope: succeeded for scope=%s", scope)
        return True

    def has_active_session(self) -> bool:
        try:
            self.get_properties()
        except AuthorizationExpiredError:
            return False
        return True

    def get_session_cookie(self) -> str | None:
        cookie = self.session.cookies.get(self.SESSION_COOKIE_NAME)
        return None if not cookie else cookie

    def get_properties(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/tenantapi/customer/properties")
        data = payload.get("Data")
        if not isinstance(data, list):
            raise IstaError("unexpected properties payload from ista")
        return data

    def get_meters(self) -> list[dict[str, Any]]:
        payload = self._request_json("POST", "/tenantapi/meter/info")
        data = payload.get("Data")
        if not isinstance(data, list):
            raise IstaError("unexpected meter info payload from ista")
        return data

    def fetch_meter_reads(self, meter_id: int) -> list[dict[str, Any]]:
        page = 1
        total = None
        all_reads: list[dict[str, Any]] = []

        while True:
            payload = self._request_json(
                "POST",
                "/tenantapi/meter/reads",
                data={
                    "meterId": meter_id,
                    "itemsPerPage": self.settings.items_per_page,
                    "page": page,
                    "billable": str(self.settings.billable_only).lower(),
                },
            )
            data = payload.get("Data") or {}
            page_reads = data.get("Data")
            if not isinstance(page_reads, list):
                raise IstaError("unexpected meter reads payload from ista")

            all_reads.extend(page_reads)

            if total is None:
                total = int(data.get("Total", len(page_reads)))

            if len(all_reads) >= total or len(page_reads) < self.settings.items_per_page:
                break

            page += 1

        return all_reads

    def select_meter(self, meters: list[dict[str, Any]]) -> dict[str, Any]:
        active_meters = [meter for meter in meters if meter.get("MeterStatus") == "Active"]
        if not active_meters:
            raise ConfigurationError("no active meters returned by ista")

        if self.settings.meter_id is not None:
            for meter in active_meters:
                if int(meter["MeterID"]) == self.settings.meter_id:
                    return meter
            raise ConfigurationError(
                f"configured meter_id={self.settings.meter_id} was not found in active meters"
            )

        if len(active_meters) == 1:
            return active_meters[0]

        heat_meters = [
            meter for meter in active_meters if "heat" in str(meter.get("TypeDescription", "")).lower()
        ]
        if len(heat_meters) == 1:
            return heat_meters[0]

        available = ", ".join(
            f"{meter.get('MeterID')}:{meter.get('TypeDescription')}" for meter in active_meters
        )
        raise ConfigurationError(
            "multiple active meters found; set ISTA_METER_ID explicitly. Available meters: "
            f"{available}"
        )

    def _discover_hidden_inputs(self, html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form", {"id": "account_login"})
        hidden_inputs: dict[str, str] = {}
        if form is None:
            return hidden_inputs
        for field in form.find_all("input", {"type": "hidden"}):
            name = field.attrs.get("name")
            if name:
                hidden_inputs[name] = field.attrs.get("value", "")
        return hidden_inputs

    def _post_login_token(self, payload: dict[str, Any]) -> bool:
        response = self.session.post(
            f"{self.settings.base_url}/auth/loginToken",
            data=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()

        text = response.text.strip().lower()
        if text == "true":
            return True
        if text == "false":
            return False

        try:
            parsed = response.json()
        except ValueError:
            return False

        if isinstance(parsed, bool):
            return parsed
        return bool(parsed)

    def _request_json(self, method: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.request(
            method,
            f"{self.settings.base_url}{path}",
            data=data,
            timeout=self.settings.request_timeout_seconds,
        )
        log.debug(
            "_request_json %s %s — HTTP %s, final_url=%s, content_type=%s",
            method, path, response.status_code, response.url,
            response.headers.get("Content-Type", ""),
        )

        # Detect redirect to login page: requests follows the redirect transparently,
        # so the final URL will differ from the requested path when the session expires.
        if "/auth/login" in response.url:
            log.warning(
                "_request_json %s %s — final URL is login page (%s) — session has expired",
                method, path, response.url,
            )
            raise AuthorizationExpiredError(
                f"ista session expired — redirected to {response.url}"
            )

        if response.status_code in (401, 403):
            log.warning(
                "_request_json %s %s — HTTP %s (authorization expired)",
                method, path, response.status_code,
            )
            raise AuthorizationExpiredError("ista authorization expired")
        response.raise_for_status()

        # Detect unexpected HTML (e.g. a login page returned with 200 after a soft redirect).
        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type:
            preview = response.text[:400].strip().replace("\n", " ")
            body_lower = response.text.lower()
            log.warning(
                "_request_json %s %s — HTML response received (Content-Type=%s). "
                "This usually means the session expired and the server returned a login page. "
                "Preview: %s",
                method, path, content_type, preview[:250],
            )
            if "login" in body_lower or "sign in" in body_lower or "password" in body_lower:
                raise AuthorizationExpiredError(
                    f"ista session expired — login page returned as HTML for {path}"
                )
            raise IstaError(f"unexpected HTML response from {path}: {preview[:200]}")

        try:
            payload = response.json()
        except ValueError as exc:
            preview = response.text[:250].strip().replace("\n", " ")
            log.error("_request_json %s %s — non-JSON response: %s", method, path, preview)
            raise IstaError(f"non-JSON response from {path}: {preview}") from exc

        if payload is False:
            log.warning(
                "_request_json %s %s — API returned `false` (session likely expired)",
                method, path,
            )
            raise AuthorizationExpiredError(
                f"ista session expired — API returned false for {path}"
            )
        if not isinstance(payload, dict):
            log.error(
                "_request_json %s %s — unexpected JSON type %s: %r",
                method, path, type(payload).__name__, str(payload)[:200],
            )
            raise IstaError(
                f"unexpected JSON response type {type(payload).__name__} from {path}"
            )

        status_code = payload.get("StatusCode")
        if status_code in (401, 403):
            log.warning(
                "_request_json %s %s — payload StatusCode %s (authorization expired)",
                method, path, status_code,
            )
            raise AuthorizationExpiredError("ista authorization expired")
        if status_code not in (None, 200):
            message = payload.get("Message") or payload.get("Error") or json.dumps(payload)[:250]
            log.error(
                "_request_json %s %s — StatusCode %s: %s",
                method, path, status_code, message,
            )
            raise IstaError(f"ista request to {path} failed with status {status_code}: {message}")
        return payload
