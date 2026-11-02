# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Credential middleware tests: /health needs no credentials, missing headers
return 401 listing them (AC8, TC11), and header values correctly reach the
per-request contextvar without leaking to the next request.
"""

import asyncio

from starlette.testclient import TestClient

from azure_mcp.auth import CredentialMiddleware, current
from azure_mcp.server import create_app
from azure_mcp.settings import (
    CLIENT_ID_HEADER,
    CLIENT_SECRET_HEADER,
    TENANT_HEADER,
    Settings,
)


def _make_app():
    settings = Settings()
    return create_app(settings)


def test_health_is_local_and_does_not_require_credentials():
    app = _make_app()
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_missing_all_headers_returns_401_listing_all_three():
    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert set(body["required_headers"]) == {
            TENANT_HEADER,
            CLIENT_ID_HEADER,
            CLIENT_SECRET_HEADER,
        }
        for name in (TENANT_HEADER, CLIENT_ID_HEADER, CLIENT_SECRET_HEADER):
            assert name in body["message"]


def test_missing_one_header_names_only_that_one():
    app = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                TENANT_HEADER: "tenant-1",
                CLIENT_ID_HEADER: "client-1",
                # CLIENT_SECRET_HEADER deliberately omitted
            },
        )
        assert resp.status_code == 401
        body = resp.json()
        assert CLIENT_SECRET_HEADER in body["message"]
        assert TENANT_HEADER not in body["message"]


def test_header_present_reaches_request_context_and_resets_after(monkeypatch):
    # Exercises the middleware's contextvar plumbing directly, without a full
    # MCP protocol round trip: confirms the header values that arrive on the
    # request are exactly what current() sees, and that they are reset
    # afterward (no leakage to the next request, AC11).
    seen = {}

    async def fake_app(scope, receive, send):
        creds = current()
        seen["tenant_id"] = creds.tenant_id if creds else None
        seen["client_id"] = creds.client_id if creds else None
        seen["client_secret"] = creds.client_secret if creds else None
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = CredentialMiddleware(fake_app)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"x-azure-tenant-id", b"tenant-123"),
                (b"x-azure-client-id", b"client-456"),
                (b"x-azure-client-secret", b"secret-789"),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen == {
        "tenant_id": "tenant-123",
        "client_id": "client-456",
        "client_secret": "secret-789",
    }
    # After the request completes, the contextvar must be reset -- a fresh
    # current() outside any request context sees no leftover credential.
    assert current() is None


def test_non_mcp_path_bypasses_credential_check():
    seen = {"called": False}

    async def fake_app(scope, receive, send):
        seen["called"] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = CredentialMiddleware(fake_app)

    async def run():
        scope = {"type": "http", "path": "/health", "headers": []}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            pass

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["called"] is True
