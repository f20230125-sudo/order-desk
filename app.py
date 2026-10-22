"""Order Desk: Flask API plus the built React app.

Vercel finds `app` here and runs it as one function. Files in public/ (the Vite build) are usually served
by the CDN before this function is reached, but a deploy built from git has no uploaded public/ for the
CDN, so this function serves those files too. Unknown /api paths get a JSON 404 and everything else gets
the app shell, so a deep link such as /orders/42 opens in the browser.
"""

import os
from pathlib import Path

import psycopg
from flask import Flask, jsonify, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from backend.api import board, discrepancies, documents, intake, orders
from backend.api.common import JsonProvider, close_db, db
from backend.config import MAX_UPLOAD_BYTES
from backend.errors import ApiError

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
INDEX_HTML = PUBLIC / "index.html"


def create_app(db_kind: str = "pooled") -> Flask:
    app = Flask(__name__, static_folder=None)
    app.json = JsonProvider(app)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 64 * 1024  # the file plus the form around it
    app.config["DB_KIND"] = db_kind
    app.teardown_appcontext(close_db)
    for module in (board, orders, intake, discrepancies, documents):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(err: ApiError):
        return err.response()

    @app.errorhandler(HTTPException)
    def _http_error(err: HTTPException):
        code = {413: "file_too_large", 404: "not_found", 405: "method_not_allowed"}.get(
            err.code, "http_error"
        )
        message = "Files up to 2 MB only." if err.code == 413 else (err.description or err.name)
        return ApiError(err.code or 500, code, message).response()

    @app.errorhandler(psycopg.errors.IntegrityError)
    def _integrity(err: psycopg.errors.IntegrityError):
        # The database's own rules are the last line: report them plainly instead of a 500.
        return ApiError(
            409,
            "conflicts_with_saved_data",
            "That would contradict data already saved.",
            details={"constraint": getattr(err.diag, "constraint_name", None)},
        ).response()

    @app.errorhandler(psycopg.OperationalError)
    def _db_down(_err):
        return ApiError(
            503, "database_waking", "The database is waking up. Try again in a few seconds."
        ).response()

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if resp.mimetype == "text/html":
            resp.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                "worker-src 'self' blob:; script-src 'self'; font-src 'self'; frame-ancestors 'none'",
            )
        return resp

    @app.get("/api/health")
    def health():
        row = db().execute("select now() as db_time, current_setting('server_version') as version").fetchone()
        return jsonify(ok=True, db_time=row["db_time"], postgres=row["version"])

    @app.route("/api/", defaults={"path": ""}, methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
    @app.route("/api/<path:path>", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
    def api_not_found(path: str):
        raise ApiError(404, "not_found", f"No API route /api/{path}")

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path: str):
        if not INDEX_HTML.is_file():
            return "The web app is not built yet: run npm --prefix web run build", 503
        if path and path != "index.html" and (PUBLIC / path).is_file():
            # Hashed names under assets/ never change content, so they can be kept for a year.
            max_age = 31536000 if path.startswith("assets/") else 3600
            return send_from_directory(PUBLIC, path, max_age=max_age)
        return send_file(INDEX_HTML, max_age=0)

    return app


# ORDER_DESK_DB=test points a local run at DATABASE_URL_TEST (the scratch Postgres); production uses the pool.
app = create_app(os.environ.get("ORDER_DESK_DB", "pooled"))
