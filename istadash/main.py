from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

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

from istadash.config import Settings
from istadash.ista_client import AuthenticationError, AuthorizationExpiredError, IstaClient
from istadash.security import clear_session_cookie, load_session_cookie, save_session_cookie
from istadash.services.sync import run_sync
from istadash.storage import Storage

PENDING_LOGINS: dict[str, dict] = {}
PENDING_TTL_MINUTES = 10


def create_app() -> Flask:
    settings = Settings.from_file()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.flask_secret_key
    app.config["SETTINGS"] = settings
    app.config["STORAGE"] = Storage(settings.database_path)

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

    @app.get("/login")
    def login_page():
        if require_onboarded_session():
            return redirect(url_for("index"))
        return render_template("login.html", stage="credentials", properties=[], meters=[], login_id=None)

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
        except AuthenticationError:
            flash("Login failed. Check your credentials and try again.", "error")
            return redirect(url_for("login_page"))
        except Exception as exc:
            flash(f"Unable to start login: {exc}", "error")
            return redirect(url_for("login_page"))

        if not properties:
            flash("No active properties were found for this account.", "error")
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

        client = IstaClient(settings)
        try:
            client.login_with_credentials(
                username=pending["username"],
                password=pending["password"],
                scope=property_scope,
            )
        except Exception as exc:
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

    @app.get("/")
    def index():
        token = require_onboarded_session()
        if not token:
            return redirect(url_for("login_page"))

        storage: Storage = app.config["STORAGE"]
        daily_usage = storage.query_daily_usage(limit=2000)
        summary = storage.get_summary()
        sync_runs = storage.list_sync_runs()
        chart_points = storage.get_chart_points()

        daily_usage_rows = [dict(row) for row in daily_usage]
        chart_series = [dict(row) for row in chart_points]
        chart_unit = next((row["unit_of_measure"] for row in chart_series if row["unit_of_measure"]), "kWh")

        return render_template(
            "index.html",
            daily_usage=daily_usage,
            daily_usage_rows=daily_usage_rows,
            summary=summary,
            sync_runs=sync_runs,
            chart_series=chart_series,
            chart_unit=chart_unit,
        )

    @app.post("/refresh")
    def refresh():
        token = require_onboarded_session()
        if not token:
            flash("Session expired. Please log in again.", "error")
            return redirect(url_for("login_page"))

        storage: Storage = app.config["STORAGE"]
        try:
            report = run_sync(settings, storage, session_cookie=token)
        except AuthorizationExpiredError:
            clear_session_cookie()
            flash("Session expired. Please log in again.", "error")
            return redirect(url_for("login_page"))
        except Exception as exc:
            flash(f"Refresh failed: {exc}", "error")
            return redirect(url_for("index"))

        flash(
            (
                f"Refresh completed for meter {report.selected_meter_id}"
                f" ({report.selected_utility or 'Unknown utility'}). "
                f"Fetched {report.fetched_count} reads and inserted {report.inserted_count} new rows."
            ),
            "success",
        )
        return redirect(url_for("index"))

    @app.get("/export.csv")
    def export_csv():
        if not require_onboarded_session():
            return redirect(url_for("login_page"))
        storage: Storage = app.config["STORAGE"]
        start_date = request.args.get("start_date") or None
        end_date = request.args.get("end_date") or None
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
        start_date = request.args.get("start_date") or None
        end_date = request.args.get("end_date") or None
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
