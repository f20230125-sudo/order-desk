"""Stored documents: the file itself (for the viewer) and what the extractor read from it."""

from flask import Blueprint, Response, jsonify

from backend.api.common import db
from backend.errors import ApiError

bp = Blueprint("documents", __name__)


@bp.get("/api/documents/<int:doc_id>")
def document(doc_id: int):
    row = (
        db()
        .execute(
            "select id, kind, filename, mime, size_bytes, extracted, extractor_version, customer_order_id, "
            "uploaded_by_role, uploaded_at from document where id = %s",
            (doc_id,),
        )
        .fetchone()
    )
    if row is None:
        raise ApiError(404, "no_such_document", f"There is no document {doc_id}.")
    return jsonify(document=row)


@bp.get("/api/documents/<int:doc_id>/file")
def document_file(doc_id: int):
    row = db().execute("select filename, mime, content from document where id = %s", (doc_id,)).fetchone()
    if row is None:
        raise ApiError(404, "no_such_document", f"There is no document {doc_id}.")
    # Served for the viewer only: never rendered as a page by the browser, and not cached by shared caches.
    disposition = "inline" if row["mime"] == "application/pdf" else "attachment"
    return Response(
        bytes(row["content"]),
        mimetype=row["mime"],
        headers={
            "Content-Disposition": f'{disposition}; filename="{row["filename"]}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
