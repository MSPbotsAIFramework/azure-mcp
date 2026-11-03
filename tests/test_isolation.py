# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""AC11/TC14: two concurrent requests carrying different tenant/client/secret
headers must never cross-contaminate -- each call's Azure AD token exchange
and response data stay scoped to that call only.

This exercises the real request path (CredentialMiddleware -> ContextVar ->
AzureClient.token()) under concurrent asyncio tasks, per the design doc's
explicit choice to test this contextvar-isolation behavior directly (there
is no frontend to "hit the backend" with, per testcase.md's quality bar).
"""

import asyncio

import httpx
import respx

from azure_mcp.auth import CredentialMiddleware, current
from azure_mcp.client import AzureClient
from azure_mcp.settings import Settings

AD_BASE = "https://login.microsoftonline.com"

TENANTS = [
    {"tenant_id": "tenant-A", "client_id": "client-A", "client_secret": "secret-A"},
    {"tenant_id": "tenant-B", "client_id": "client-B", "client_secret": "secret-B"},
]


def _scope(tenant: dict) -> dict:
    return {
        "type": "http",
        "path": "/mcp",
        "headers": [
            (b"x-azure-tenant-id", tenant["tenant_id"].encode()),
            (b"x-azure-client-id", tenant["client_id"].encode()),
            (b"x-azure-client-secret", tenant["client_secret"].encode()),
        ],
    }


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def test_concurrent_requests_do_not_cross_contaminate_credentials():
    """Two tenants' requests run through the middleware concurrently. Each
    one's downstream handler reads current() (the ContextVar the middleware
    set for THAT request) and exchanges a token for it. The handlers are
    interleaved via asyncio.sleep so the two requests genuinely overlap in
    time, not just in program order.
    """
    settings = Settings(max_retries=0)
    observed: dict[str, dict] = {}

    with respx.mock(assert_all_called=True) as mock:
        for t in TENANTS:
            mock.post(f"{AD_BASE}/{t['tenant_id']}/oauth2/v2.0/token").mock(
                return_value=httpx.Response(
                    200, json={"access_token": f"token-for-{t['tenant_id']}"}
                )
            )

        async def downstream(scope, receive, send):
            creds = current()
            # Yield control so the other concurrent request's middleware call
            # can run and set/observe its own ContextVar copy in between.
            await asyncio.sleep(0.01)
            async with AzureClient(creds, settings) as client:
                token = await client.token()
            # current() must still show THIS request's own credentials after
            # the await, not whatever the other concurrent request set.
            observed[creds.tenant_id] = {
                "client_id_after_await": current().client_id,
                "token": token,
            }
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = CredentialMiddleware(downstream)

        async def run_one(tenant: dict):
            sent = []

            async def send(message):
                sent.append(message)

            await middleware(_scope(tenant), _receive, send)

        await asyncio.gather(*(run_one(t) for t in TENANTS))

    for t in TENANTS:
        result = observed[t["tenant_id"]]
        assert result["client_id_after_await"] == t["client_id"]
        assert result["token"] == f"token-for-{t['tenant_id']}"

    assert current() is None


async def test_contextvar_is_request_scoped_under_concurrent_tasks():
    """Lower-level check directly on the ContextVar plumbing: concurrent
    asyncio tasks each setting different credentials in their own copied
    context never observe each other's values (Python copies the context
    per task, which is what makes the per-request isolation correct).
    """
    from azure_mcp import auth

    results: dict[str, str] = {}

    async def worker(name: str, tenant_id: str):
        token = auth._current.set(
            auth.Credentials(tenant_id=tenant_id, client_id="c", client_secret="s")
        )
        try:
            await asyncio.sleep(0.01)
            results[name] = auth.current().tenant_id
        finally:
            auth._current.reset(token)

    await asyncio.gather(worker("a", "tenant-A"), worker("b", "tenant-B"))

    assert results == {"a": "tenant-A", "b": "tenant-B"}
    # No leakage outside either task's context.
    assert auth.current() is None
