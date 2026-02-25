"""
CheckEasy API - Authentication & Rate Limiting Middleware
Adds API key authentication and rate limiting on top of existing endpoints.
"""

import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Endpoints that NEVER require auth (monitoring, docs, static pages)
PUBLIC_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# Prefixes for static assets served by FastAPI (always public)
PUBLIC_PREFIXES = (
    "/static/",
    "/templates-static/",
)

# HTML pages served as FileResponse (admin tools) - public to load the page,
# but the AJAX calls they make to /api/* will require auth
ADMIN_HTML_PATHS = {
    "/",
    "/admin",
    "/tester",
    "/rapport-tester",
    "/logs-viewer",
    "/prompts-admin",
    "/scoring-config",
    "/parcourtest.json",
}


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    API key authentication middleware.

    - If API_SECRET_KEY is NOT set in env, all requests pass through (backward compatible).
    - If API_SECRET_KEY IS set, requires X-API-Key header on protected endpoints.
    - Public paths (health, docs, admin HTML pages) are always accessible.
    """

    def __init__(self, app):
        super().__init__(app)
        self.api_key = os.environ.get("API_SECRET_KEY", "").strip()

    async def dispatch(self, request: Request, call_next):
        # If no API key configured, skip auth entirely (backward compatible)
        if not self.api_key:
            return await call_next(request)

        path = request.url.path

        # Allow CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow public paths
        if path in PUBLIC_PATHS or path in ADMIN_HTML_PATHS:
            return await call_next(request)

        # Allow static asset prefixes
        if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        # Allow WebSocket connections (logs viewer)
        if path.startswith("/ws/"):
            return await call_next(request)

        # Check API key on all other endpoints
        provided_key = request.headers.get("X-API-Key", "")
        if provided_key != self.api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key. Provide X-API-Key header."}
            )

        return await call_next(request)
