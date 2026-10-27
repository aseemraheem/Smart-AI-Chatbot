"""Consistent JSON error responses for the API."""
import logging
import sqlite3

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from app.services.ai_service import AIServiceError

logger = logging.getLogger(__name__)

_HTTP_MESSAGES = {
    404: "Resource not found.",
    405: "Method not allowed.",
    413: "The request is too large.",
    415: "Send the request body as JSON.",
}


class ApiError(Exception):
    """Raised by routes for validation problems; becomes a JSON error."""

    def __init__(self, message: str, status: int = 400, code: str = "bad_request"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def error_response(message: str, status: int, code: str):
    return jsonify({"error": {"message": message, "code": code}}), status


def init_app(app):
    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.message, exc.status, exc.code)

    @app.errorhandler(AIServiceError)
    def handle_ai_error(exc):
        return error_response(exc.message, exc.status, exc.code)

    @app.errorhandler(sqlite3.Error)
    def handle_db_error(exc):
        logger.exception("Database error")
        return error_response("A database error occurred. Please try again.", 500, "database_error")

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if request.path.startswith("/api/"):
            message = _HTTP_MESSAGES.get(exc.code, exc.description or exc.name)
            return error_response(message, exc.code, exc.name.lower().replace(" ", "_"))
        return exc

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Log details server-side; never leak them to the browser.
        logger.exception("Unexpected error")
        return error_response("Something went wrong on the server.", 500, "server_error")
