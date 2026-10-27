"""Lightweight, dependency-free request hardening.

The app deliberately avoids paid infrastructure, so this module provides the
baseline protections a public Flask deployment needs without adding services:
origin-checked state changes, in-process rate limiting, and strict headers.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, current_app, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_RATE_BUCKETS: dict[tuple[str, str], deque] = defaultdict(deque)
_RATE_LOCK = threading.Lock()
_RATE_MAX_KEYS = 5000

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def _same_origin_request() -> bool:
    fetch_site = (request.headers.get("Sec-Fetch-Site") or "").strip().lower()
    if fetch_site == "cross-site":
        return False

    origin = request.headers.get("Origin")
    if origin and origin != "null":
        return urlsplit(origin).netloc == request.host

    referer = request.headers.get("Referer")
    if referer:
        return urlsplit(referer).netloc == request.host

    # Non-browser clients (curl, tests, mobile apps) do not send either header.
    return True


def _client_key() -> str:
    # ProxyFix has already rewritten remote_addr from the trusted proxy chain.
    return request.remote_addr or "unknown"


def _prune_buckets(now: float) -> None:
    if len(_RATE_BUCKETS) <= _RATE_MAX_KEYS:
        return
    stale = [key for key, bucket in _RATE_BUCKETS.items() if not bucket or now - bucket[-1] > 3600]
    for key in stale:
        _RATE_BUCKETS.pop(key, None)


def rate_limit(limit: int, window_seconds: int, scope: str | None = None):
    """Allow ``limit`` requests per client per ``window_seconds``."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_app.config.get("RATELIMIT_ENABLED", True):
                return view(*args, **kwargs)

            name = scope or request.endpoint or view.__name__
            key = (_client_key(), name)
            now = time.monotonic()
            with _RATE_LOCK:
                bucket = _RATE_BUCKETS[key]
                while bucket and now - bucket[0] > window_seconds:
                    bucket.popleft()
                if len(bucket) >= limit:
                    retry_after = max(1, int(window_seconds - (now - bucket[0])))
                    current_app.logger.warning("Rate limit hit for %s on %s", key[0], name)
                    if request.path.startswith("/api/") or request.is_json:
                        response = jsonify(
                            {"error": "rate_limited", "retry_after": retry_after}
                        )
                        response.status_code = 429
                    else:
                        response = current_app.response_class(
                            f"Too many requests. Retry in {retry_after} seconds.",
                            status=429,
                            mimetype="text/plain",
                        )
                    response.headers["Retry-After"] = str(retry_after)
                    return response
                bucket.append(now)
                _prune_buckets(now)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def install_security(app) -> None:
    if app.config.get("TRUST_PROXY_HEADERS", True):
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1
        )

    @app.before_request
    def _reject_cross_site_mutations():
        if request.method in SAFE_METHODS:
            return None
        if not current_app.config.get("ORIGIN_CHECK_ENABLED", True):
            return None
        if not _same_origin_request():
            current_app.logger.warning(
                "Blocked cross-origin %s to %s", request.method, request.path
            )
            abort(403)
        return None

    @app.after_request
    def _apply_security_headers(response):
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.is_secure:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if request.path.startswith(("/roadmap/", "/dashboard", "/questions/", "/api/")):
            headers.setdefault("Cache-Control", "no-store")
        return response
