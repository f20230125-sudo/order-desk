"""One error shape for every API response: {"error": {"code": ..., "message": ..., "details": ...}}."""

from flask import jsonify


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: object | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details

    def response(self):
        body = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            body["error"]["details"] = self.details
        return jsonify(body), self.status
