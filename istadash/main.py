from __future__ import annotations

import importlib.metadata
import json
import logging
import logging.handlers
import os
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests
from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from istadash.config import DATA_DIR, Settings
from istadash.ista_client import AuthenticationError, AuthorizationExpiredError, IstaClient
from istadash.security import clear_session_cookie, load_session_cookie, save_session_cookie
from istadash.services.sync import run_sync
from istadash.storage import Storage

# ---------------------------------------------------------------------------
# File-based logging - persists across page reloads
# ---------------------------------------------------------------------------
LOG_FILE: Path = DATA_DIR / "istadash.log"


def _setup_log_capture() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return
    # Truncate on startup so each run starts with a clean log.
    LOG_FILE.write_text("", encoding="utf-8")
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"))
    handler.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

PENDING_LOGINS: dict[str, dict] = {}
PENDING_TTL_MINUTES = 10

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Background sync state  (idle → running → done | failed | auth_expired)
# ---------------------------------------------------------------------------
_sync_lock = threading.Lock()
_sync_state: dict = {
    "status": "idle",
    "message": "",
    "started_at": None,
    "result": None,
}

# ---------------------------------------------------------------------------
# Query result cache — invalidated after every successful sync
# ---------------------------------------------------------------------------
_QUERY_CACHE_TTL = timedelta(seconds=60)
_query_cache: dict = {"ts": None, "summary": None, "chart": None}


def _invalidate_query_cache() -> None:
    _query_cache["ts"] = None


def _get_cached_summary(storage: Storage):
    now = datetime.now(UTC)
    if _query_cache["ts"] and now - _query_cache["ts"] < _QUERY_CACHE_TTL:
        return _query_cache["summary"]
    _query_cache["summary"] = storage.get_summary()
    _query_cache["chart"] = storage.get_chart_points()
    _query_cache["ts"] = now
    return _query_cache["summary"]


def _get_cached_chart(storage: Storage):
    now = datetime.now(UTC)
    if _query_cache["ts"] and now - _query_cache["ts"] < _QUERY_CACHE_TTL:
        return _query_cache["chart"]
    _query_cache["summary"] = storage.get_summary()
    _query_cache["chart"] = storage.get_chart_points()
    _query_cache["ts"] = now
    return _query_cache["chart"]

# ---------------------------------------------------------------------------
# Update check - cached for 2 minutes; also runs on every startup
# ---------------------------------------------------------------------------
_CURRENT_VERSION: str = importlib.metadata.version("istadash")
_RELEASES_URL = "https://api.github.com/repos/asadislam94/istadash/releases/latest"
_RELEASE_PAGE = "https://github.com/asadislam94/istadash/releases"

_update_cache: dict = {"checked_at": None, "latest": None, "url": None}
_UPDATE_CACHE_TTL = timedelta(minutes=2)


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except ValueError:
        return (0,)


def check_for_update() -> dict | None:
    """Return dict(latest, url) if a newer release exists, else None."""
    now = datetime.now(UTC)
    if _update_cache["checked_at"] and now - _update_cache["checked_at"] < _UPDATE_CACHE_TTL:
        log.debug("check_for_update: returning cached result (checked at %s)", _update_cache["checked_at"])
        return _update_cache["latest"]

    log.info("check_for_update: checking for new version (current: v%s)", _CURRENT_VERSION)
    try:
        resp = requests.get(_RELEASES_URL, timeout=5, headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        data = resp.json()
        tag = data.get("tag_name", "")
        html_url = data.get("html_url", _RELEASE_PAGE)
        log.info("check_for_update: current=v%s latest=%s", _CURRENT_VERSION, tag)
        if _version_tuple(tag) > _version_tuple(_CURRENT_VERSION):
            log.debug("check_for_update: update available! Latest version: %s", tag)
            result = {"latest": tag.lstrip("v"), "url": html_url}
        else:
            log.debug("check_for_update: no update available")
            result = None
    except Exception as exc:
        log.warning("check_for_update: request failed — %s", exc)
        result = None

    _update_cache["checked_at"] = now
    _update_cache["latest"] = result
    return result


def _parse_date(value: str | None) -> str | None:
    """Validate and return a YYYY-MM-DD date string, or None if invalid."""
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        return None


def create_app() -> Flask:
    settings = Settings.from_file()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.flask_secret_key
    app.config["SETTINGS"] = settings
    app.config["STORAGE"] = Storage(settings.database_path)
    _setup_log_capture()

    # Warm the update cache in the background so the first browser request
    # to /api/update-check never has to wait on the 5 s network timeout.
    threading.Thread(target=check_for_update, daemon=True).start()

    def cleanup_pending_logins() -> None:
        cutoff = datetime.now(UTC) - timedelta(minutes=PENDING_TTL_MINUTES)
        expired = [k for k, v in PENDING_LOGINS.items() if v["created_at"] < cutoff]
        for key in expired:
            del PENDING_LOGINS[key]

    def require_onboarded_session() -> str | None:
        token = load_session_cookie()
        if not token:
            return None
        if not settings.is_onboarded():
            return None
        return token

    def active_properties_only(properties: list[dict]) -> list[dict]:
        return [prop for prop in properties if prop.get("Active", True)]

    def active_meters_only(meters: list[dict]) -> list[dict]:
        return [meter for meter in meters if meter.get("MeterStatus") == "Active"]

    @app.get("/favicon.ico")
    def favicon():
        return app.send_static_file("favicon.ico")

    @app.get("/login")
    def login_page():
        if require_onboarded_session():
            return redirect(url_for("index"))
        from istadash.security import _has_keyring
        return render_template("login.html", stage="credentials", properties=[], meters=[], login_id=None, no_keyring=not _has_keyring())

    @app.post("/login/start")
    def login_start():
        cleanup_pending_logins()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Please enter both username and password.", "error")
            return redirect(url_for("login_page"))

        client = IstaClient(settings)
        try:
            client.login_with_credentials(username=username, password=password)
            properties = active_properties_only(client.get_properties())
        except AuthenticationError as exc:
            log.warning("login_start: authentication rejected for %s — %s", username, exc)
            flash("Login failed. Check your credentials and try again.", "error")
            return redirect(url_for("login_page"))
        except Exception as exc:
            log.exception("login_start: unexpected error for %s", username)
            flash(f"Unable to start login: {exc}", "error")
            return redirect(url_for("login_page"))

        if not properties:
            flash("No active properties were found for this account.", "error")
            return redirect(url_for("login_page"))

        session_cookie = client.get_session_cookie()
        if not session_cookie:
            flash("Login succeeded but no session token was returned.", "error")
            return redirect(url_for("login_page"))

        login_id = secrets.token_urlsafe(24)
        PENDING_LOGINS[login_id] = {
            "username": username,
            "password": password,
            "created_at": datetime.now(UTC),
        }

        if len(properties) == 1:
            return redirect(url_for("login_select_meter", login_id=login_id, property_scope=str(properties[0]["CustId"])))

        return render_template(
            "login.html",
            stage="property",
            properties=properties,
            meters=[],
            login_id=login_id,
            selected_property_scope=None,
        )

    @app.get("/login/meter")
    def login_select_meter():
        cleanup_pending_logins()
        login_id = request.args.get("login_id") or ""
        property_scope = request.args.get("property_scope") or ""
        pending = PENDING_LOGINS.get(login_id)
        if not pending:
            flash("Login session expired. Please sign in again.", "error")
            return redirect(url_for("login_page"))
        if not property_scope:
            flash("Please choose a property.", "error")
            return redirect(url_for("login_page"))

        client = IstaClient(settings)
        try:
            client.login_with_credentials(
                username=pending["username"],
                password=pending["password"],
                scope=property_scope,
            )
            meters = active_meters_only(client.get_meters())
        except Exception as exc:
            log.exception("login_select_meter: error loading meters")
            flash(f"Unable to load meters: {exc}", "error")
            return redirect(url_for("login_page"))

        if not meters:
            flash("No active meters were found for the selected property.", "error")
            return redirect(url_for("login_page"))

        if len(meters) == 1:
            return redirect(
                url_for(
                    "login_complete",
                    login_id=login_id,
                    property_scope=property_scope,
                    meter_id=str(meters[0]["MeterID"]),
                )
            )

        return render_template(
            "login.html",
            stage="meter",
            properties=[],
            meters=meters,
            login_id=login_id,
            selected_property_scope=property_scope,
        )

    @app.get("/login/complete")
    def login_complete():
        cleanup_pending_logins()
        login_id = request.args.get("login_id") or ""
        property_scope = request.args.get("property_scope") or ""
        meter_id = request.args.get("meter_id") or ""
        pending = PENDING_LOGINS.get(login_id)
        if not pending:
            flash("Login session expired. Please sign in again.", "error")
            return redirect(url_for("login_page"))
        if not property_scope or not meter_id:
            flash("Please choose both property and meter.", "error")
            return redirect(url_for("login_page"))

        first_time_setup = not settings.is_onboarded()

        # Re-authenticate with credentials + scope to obtain a properly scoped
        # session cookie.  Credentials are held in-memory only (PENDING_LOGINS)
        # and are never written to disk.
        client = IstaClient(settings)
        try:
            client.login_with_credentials(
                username=pending["username"],
                password=pending["password"],
                scope=property_scope,
            )
        except Exception as exc:
            log.exception("login_complete: re-authentication failed")
            flash(f"Unable to complete login: {exc}", "error")
            return redirect(url_for("login_page"))

        cookie_value = client.get_session_cookie()
        if not cookie_value:
            flash("Login succeeded but no secure session token was returned.", "error")
            return redirect(url_for("login_page"))

        save_session_cookie(cookie_value)
        settings.update_selection(meter_id=int(meter_id), property_scope=str(property_scope))
        PENDING_LOGINS.pop(login_id, None)

        if first_time_setup:
            storage: Storage = app.config["STORAGE"]
            try:
                report = run_sync(settings, storage, session_cookie=cookie_value)
                flash(
                    (
                        "Login complete. Initial refresh finished automatically: "
                        f"fetched {report.fetched_count}, inserted {report.inserted_count}."
                    ),
                    "success",
                )
            except Exception as exc:
                log.exception("login_complete: initial auto-refresh failed")
                flash(
                    "Login complete, but initial auto-refresh failed. "
                    f"You can retry from the dashboard. Details: {exc}",
                    "error",
                )
        else:
            flash("Login complete. Secure session and meter selection saved.", "success")

        return redirect(url_for("index"))

    @app.get("/logout")
    def logout():
        clear_session_cookie()
        session.clear()
        flash("Secure session cleared. Please log in again.", "success")
        return redirect(url_for("login_page"))

    @app.post("/clear-session")
    def clear_session_route():
        """Explicit user-triggered session clear — use when auto re-login detection fails."""
        log.info(
            "clear_session_route: user manually cleared session — "
            "clearing stored token and redirecting to login"
        )
        clear_session_cookie()
        session.clear()
        flash(
            "Session cleared. Please log in again to reconnect to ista.",
            "success",
        )
        return redirect(url_for("login_page"))

    @app.get("/")
    def index():
        token = require_onboarded_session()
        if not token:
            return redirect(url_for("login_page"))

        storage: Storage = app.config["STORAGE"]
        daily_usage = storage.query_daily_usage(limit=2000)
        summary = _get_cached_summary(storage)
        sync_runs = storage.list_sync_runs()
        chart_points = _get_cached_chart(storage)

        daily_usage_rows = [dict(row) for row in daily_usage]
        chart_series = [dict(row) for row in chart_points]
        chart_unit = next((row["unit_of_measure"] for row in chart_series if row["unit_of_measure"]), "kWh")

        last_sync = sync_runs[0] if sync_runs else None
        last_synced_at = last_sync["finished_at"] if last_sync and last_sync["status"] == "success" else None

        return render_template(
            "index.html",
            daily_usage=daily_usage,
            daily_usage_rows=daily_usage_rows,
            summary=summary,
            sync_runs=sync_runs,
            chart_series=chart_series,
            chart_unit=chart_unit,
            current_version=_CURRENT_VERSION,
            last_synced_at=last_synced_at,
        )

    @app.post("/refresh")
    def refresh():
        token = require_onboarded_session()
        if not token:
            return Response(
                json.dumps({"error": "auth", "message": "Session expired"}),
                status=401,
                mimetype="application/json",
            )

        with _sync_lock:
            if _sync_state["status"] == "running":
                return Response(
                    json.dumps({"status": "running", "message": "Sync already in progress"}),
                    status=409,
                    mimetype="application/json",
                )
            _sync_state.update({
                "status": "running",
                "message": "Connecting to ista…",
                "started_at": datetime.now(UTC).isoformat(),
                "result": None,
            })

        storage: Storage = app.config["STORAGE"]

        def _run_bg() -> None:
            try:
                report = run_sync(settings, storage, session_cookie=token)
                _invalidate_query_cache()
                msg = (
                    f"Fetched {report.fetched_count} reads, "
                    f"{report.inserted_count} new rows for meter {report.selected_meter_id}."
                )
                with _sync_lock:
                    _sync_state.update({
                        "status": "done",
                        "message": msg,
                        "result": {
                            "meter_id": report.selected_meter_id,
                            "utility": report.selected_utility,
                            "fetched": report.fetched_count,
                            "inserted": report.inserted_count,
                        },
                    })
                log.info("refresh (bg): %s", msg)
            except AuthorizationExpiredError as exc:
                clear_session_cookie()
                with _sync_lock:
                    _sync_state.update({"status": "auth_expired", "message": "Session expired."})
                log.warning("refresh (bg): session expired — %s", exc)
            except Exception as exc:
                with _sync_lock:
                    _sync_state.update({"status": "failed", "message": str(exc)})
                log.exception("refresh (bg): unexpected error — %s", exc)

        threading.Thread(target=_run_bg, daemon=True).start()
        return Response(
            json.dumps({"status": "started"}),
            status=202,
            mimetype="application/json",
        )

    @app.get("/api/sync-status")
    def api_sync_status():
        with _sync_lock:
            state = dict(_sync_state)
        return Response(json.dumps(state), mimetype="application/json")

    @app.get("/api/summary")
    def api_summary():
        if not require_onboarded_session():
            return Response(json.dumps({"error": "auth"}), status=401, mimetype="application/json")
        storage: Storage = app.config["STORAGE"]
        summary = storage.get_summary()
        sync_runs = storage.list_sync_runs(limit=1)
        last_sync = sync_runs[0] if sync_runs else None
        last_synced_at = last_sync["finished_at"] if last_sync and last_sync["status"] == "success" else None
        return Response(
            json.dumps(dict(summary) | {"last_synced_at": last_synced_at}),
            mimetype="application/json",
        )

    @app.get("/export.csv")
    def export_csv():
        if not require_onboarded_session():
            return redirect(url_for("login_page"))
        storage: Storage = app.config["STORAGE"]
        start_date = _parse_date(request.args.get("start_date"))
        end_date = _parse_date(request.args.get("end_date"))
        export_path = storage.export_readings_csv(
            settings.export_dir / "readings.csv",
            start_date=start_date,
            end_date=end_date,
        )
        return send_file(Path(export_path), as_attachment=True, download_name="readings.csv")

    @app.get("/export.json")
    def export_json():
        if not require_onboarded_session():
            return redirect(url_for("login_page"))
        storage: Storage = app.config["STORAGE"]
        start_date = _parse_date(request.args.get("start_date"))
        end_date = _parse_date(request.args.get("end_date"))
        usage_rows = [dict(row) for row in storage.query_daily_usage(
            date_from=start_date,
            date_to=end_date,
            limit=50000,
        )]
        payload = json.dumps(usage_rows, indent=2)
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=usage.json"},
        )

    @app.get("/logs")
    def logs_read():
        """Return the last N lines of the log file plus total line count."""
        n = min(int(request.args.get("n", 200)), 2000)
        try:
            text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
            all_lines = [ln for ln in text.splitlines() if ln.strip()]
            total = len(all_lines)
            lines = all_lines[-n:]
        except FileNotFoundError:
            total = 0
            lines = []
        return Response(json.dumps({"lines": lines, "total": total}), mimetype="application/json")

    @app.get("/api/update-check")
    def api_update_check():
        """Run (or return cached) update check. Called by the frontend after page load."""
        result = check_for_update()
        return Response(
            json.dumps({"update": result, "current": _CURRENT_VERSION}),
            mimetype="application/json",
        )

    return app


if __name__ == "__main__":
    import os

    _app = create_app()
    _settings = _app.config["SETTINGS"]
    # FLASK_DEBUG env var (set by the VS Code launch config) overrides config.json
    _debug = bool(os.environ.get("FLASK_DEBUG", "")) or _settings.flask_debug
    _app.run(
        host=_settings.flask_host,
        port=_settings.flask_port,
        debug=_debug,
    )
