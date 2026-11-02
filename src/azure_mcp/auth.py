# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Per-request Azure AD (Entra ID) credentials, taken only from request headers.

The gateway sends each tenant's app-registration credentials on every request.
They live in a ContextVar for the duration of that request and are never
stored anywhere else -- no environment-variable fallback, no module-level
cache (see client.py: the derived access token is exchanged fresh on every
call, never cached across requests, for the same reason).
"""

import contextvars
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .settings import CLIENT_ID_HEADER, CLIENT_SECRET_HEADER, REQUIRED_HEADERS, TENANT_HEADER


@dataclass(frozen=True)
class Credentials:
    tenant_id: str
    client_id: str
    client_secret: str


_current: contextvars.ContextVar[Credentials | None] = contextvars.ContextVar(
    "azure_credentials", default=None
)


def current() -> Credentials | None:
    return _current.get()


def _reject(missing: list[str]) -> JSONResponse:
    return JSONResponse(
        {
            "error": "Missing credentials",
            "message": f"Missing required Azure headers: {', '.join(missing)}.",
            "required_headers": REQUIRED_HEADERS,
        },
        status_code=401,
    )


class CredentialMiddleware:
    """Reads the three Azure AD headers on /mcp requests and binds them to the
    request context. Returns 401 (never 500) when any are missing, without
    calling Azure (AC8).
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        headers = Request(scope).headers
        values = {name: (headers.get(name) or "").strip() for name in REQUIRED_HEADERS}
        missing = [name for name in REQUIRED_HEADERS if not values[name]]
        if missing:
            await _reject(missing)(scope, receive, send)
            return

        token = _current.set(
            Credentials(
                tenant_id=values[TENANT_HEADER],
                client_id=values[CLIENT_ID_HEADER],
                client_secret=values[CLIENT_SECRET_HEADER],
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
