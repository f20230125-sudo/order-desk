"""Decide what an uploaded file is from its first bytes, not its name or the browser's claim."""

from backend.extract.email import extract_email
from backend.extract.pdf import extract_pdf

EMAIL_HEADERS = (
    b"from:",
    b"to:",
    b"subject:",
    b"date:",
    b"message-id:",
    b"received:",
    b"mime-version:",
    b"return-path:",
    b"content-type:",
)


def sniff(data: bytes) -> str | None:
    """'application/pdf', 'message/rfc822' or None."""
    if data[:5] == b"%PDF-":
        return "application/pdf"
    head = data[:2048].lstrip().lower()
    first_lines = head.split(b"\n", 6)[:6]
    if sum(1 for line in first_lines if line.startswith(EMAIL_HEADERS)) >= 2:
        return "message/rfc822"
    return None


def extract(data: bytes, kind: str | None = None) -> tuple[str, dict]:
    mime = sniff(data)
    if mime == "application/pdf":
        return mime, extract_pdf(data, kind if kind != "shipment_email" else None)
    if mime == "message/rfc822":
        return mime, extract_email(data)
    raise ValueError("not a PDF or an email file")
