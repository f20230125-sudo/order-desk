"""Order Desk: Flask API plus the built React app.

Vercel finds `app` here and runs it as one function. Files in public/ (the Vite build) are served by the
CDN before this function is reached; every other path lands here. Unknown /api paths get a JSON 404 and
everything else gets the app shell, so a deep link such as /orders/42 opens in the browser.
"""

from pathlib import Path

from flask import Flask, jsonify, send_file
from werkzeug.exceptions import HTTPException

from backend.config import MAX_UPLOAD_BYTES
from backend.db.conn import connect
from backend.errors import ApiError

ROOT = Path(__file__).resolve().parent
INDEX_HTML = ROOT / "public" / "index.html"

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


@app.errorhandler(ApiError)
def _api_error(err: ApiError):
    return err.response()


@app.errorhandler(HTTPException)
def _http_error(err: HTTPException):
    code = {413: "file_too_large", 404: "not_found", 405: "method_not_allowed"}.get(err.code, "http_error")
    return ApiError(err.code or 500, code, err.description or err.name).response()


@app.get("/api/health")
def health():
    with connect() as conn:
        row = conn.execute("select now() as db_time, current_setting('server_version') as version").fetchone()
    return jsonify(ok=True, db_time=row["db_time"].isoformat(), postgres=row["version"])


@app.route("/api/", defaults={"path": ""})
@app.route("/api/<path:path>")
def api_not_found(path: str):
    raise ApiError(404, "not_found", f"No API route /api/{path}")


@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def spa(path: str):
    if not INDEX_HTML.is_file():
        return "The web app is not built yet: run npm --prefix web run build", 503
    return send_file(INDEX_HTML, max_age=0)
