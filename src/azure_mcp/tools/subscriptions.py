# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Subscriptions: which Azure subscriptions the app registration can see, and
details of one of them (AC1, AC2, AC3).
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import AzureClient
from ..errors import AzureApiError
from ..settings import Settings
from ._common import READ, run

API_VERSION = "2022-12-01"


def _project(sub: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": sub.get("id"),
        "subscriptionId": sub.get("subscriptionId"),
        "displayName": sub.get("displayName"),
        "state": sub.get("state"),
        "tenantId": sub.get("tenantId"),
    }


def register(mcp: FastMCP, settings: Settings) -> None:

    @mcp.tool(annotations=READ)
    async def azure_list_subscriptions() -> str:
        """List the Azure subscriptions visible to the credentialed app registration.

        Returns each subscription's id, subscriptionId, displayName and state.
        Use subscriptionId (not the full id path) as the subscription_id argument
        to every other tool in this service.
        """

        async def handler(client: AzureClient) -> dict[str, Any]:
            data = await client.get("/subscriptions", {"api-version": API_VERSION})
            rows = data.get("value", []) if isinstance(data, dict) else []
            items = [_project(s) for s in rows]
            return {"items": items, "count": len(items), "has_more": bool(data.get("nextLink"))}

        return await run(settings, handler)

    @mcp.tool(annotations=READ)
    async def azure_get_subscription(subscription_id: str) -> str:
        """Get one Azure subscription's id, displayName, state and tenantId.

        Returns a structured not_found error naming the subscription if it is
        unknown or not accessible with the current credentials.
        """

        async def handler(client: AzureClient) -> dict[str, Any]:
            try:
                data = await client.get(
                    f"/subscriptions/{subscription_id}", {"api-version": API_VERSION}
                )
            except AzureApiError as exc:
                if exc.code == "not_found":
                    raise AzureApiError(
                        "not_found",
                        f"Subscription '{subscription_id}' not found or not accessible "
                        f"with the current credentials.",
                        False,
                        exc.status,
                    ) from exc
                raise
            return _project(data)

        return await run(settings, handler)
