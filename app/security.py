"""CSRF protection, a small rate limiter, and security headers."""
import hmac
import secrets
import time
from collections import defaultdict, deque
from threading import Lock

from flask import request, session

from app.errors import error_response

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# All scripts/styles are served from our own origin (libraries are vendored),
# so the policy can be strict. Remote images in Markdown are blocked on purpose.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)


def get_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


class RateLimiter:
    """Sliding-window limiter kept in memory (fine for one local process)."""

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit, self.window = limit, window_seconds
        self._hits = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def init_app(app):
    app.extensions["rate_limiter"] = RateLimiter(app.config["RATE_LIMIT_PER_MINUTE"])

    @app.before_request
    def check_csrf():
        if request.method in SAFE_METHODS or not request.path.startswith("/api/"):
            return None
        sent = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
            return error_response("Security check failed. Reload the page and try again.", 403, "csrf_failed")
        return None

    @app.after_request
    def add_headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
