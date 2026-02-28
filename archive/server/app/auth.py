"""API key authentication middleware.

Gates /api/ and /ws/ routes with a shared secret from config.API_KEY.
Static files and other routes pass through. If API_KEY is empty, all
requests pass through (dev mode).
"""

import secrets
from urllib.parse import parse_qs, urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import API_KEY


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only gate API and WebSocket paths
        if not (path.startswith("/api/") or path.startswith("/ws/")):
            return await call_next(request)

        # Dev mode: no key configured, allow everything
        if not API_KEY:
            return await call_next(request)

        # WebSocket: check ?token= query parameter
        if path.startswith("/ws/"):
            qs = parse_qs(urlparse(str(request.url)).query)
            token = qs.get("token", [""])[0]
            if not token or not secrets.compare_digest(token, API_KEY):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Invalid or missing API key"},
                )
            return await call_next(request)

        # HTTP: check Authorization: Bearer <token>
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = ""

        if not token or not secrets.compare_digest(token, API_KEY):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)
