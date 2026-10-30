"""Security middleware -- HTTP security headers and request guards."""

from __future__ import annotations

import os
import re
from typing import Any

# Mark's desktop app shows the OpenJarvis UI inside its own loopback window.
# Setting this to a CSP source list (e.g. ``http://127.0.0.1:*``) replaces
# ``X-Frame-Options: DENY`` with ``frame-ancestors <sources>``. Unset = DENY.
FRAME_ANCESTORS_ENV = "OPENJARVIS_FRAME_ANCESTORS"
_LOOPBACK_SOURCE = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:(\d{1,5}|\*))?$")


def allowed_frame_ancestors() -> str:
    """Return validated loopback-only frame ancestors from the env, or ``""``."""
    sources = os.environ.get(FRAME_ANCESTORS_ENV, "").split()
    if sources and all(_LOOPBACK_SOURCE.match(source) for source in sources):
        return " ".join(sources)
    return ""


__all__ = [
    "FRAME_ANCESTORS_ENV",
    "SECURITY_HEADERS",
    "allowed_frame_ancestors",
    "create_security_middleware",
]


def create_security_middleware() -> Any:
    """Create a FastAPI middleware that adds security headers.

    Returns a middleware class/callable, or None if FastAPI is not available.

    Headers added:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Strict-Transport-Security: max-age=31536000; includeSubDomains
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: camera=(), microphone=(), geolocation=()

    OPTIONS requests are passed through without headers so that
    CORS preflight is not blocked.
    """
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response
    except ImportError:
        return None

    frame_ancestors = allowed_frame_ancestors()

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            # Let CORS preflight requests pass through without
            # security headers that would conflict with CORS.
            if request.method == "OPTIONS":
                return await call_next(request)

            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            if not frame_ancestors:
                response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            # microphone=(self): the chat UI records voice input from this same
            # origin. An empty allowlist blocked its own feature.
            response.headers["Permissions-Policy"] = (
                "camera=(), microphone=(self), geolocation=()"
            )
            # media-src blob: lets the UI play synthesized speech, which arrives
            # as a blob URL; default-src alone refused it.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "media-src 'self' blob:"
            ) + (f"; frame-ancestors {frame_ancestors}" if frame_ancestors else "")
            return response

    return SecurityHeadersMiddleware


# Also export the header values as constants for testing
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval'; media-src 'self' blob:"
    ),
}
