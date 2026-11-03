# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Azure Resource Health / Service Health events for a subscription (AC5):
service issues, planned maintenance, and health/security advisories.
"""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import AzureClient
from ..settings import Settings
from ._common import READ, cap, page, run

API_VERSION = "2022-10-01"


def _project(event: dict[str, Any]) -> dict[str, Any]:
    props = event.get("properties") or {}
    return {
        "id": event.get("id"),
        "eventType": props.get("eventType"),
        "status": props.get("status"),
        "title": props.get("title") or props.get("description"),
        "summary": props.get("summary"),
        "impactStartTime": props.get("impactStartTime"),
        "impactMitigationTime": props.get("impactMitigationTime"),
    }


def register(mcp: FastMCP, settings: Settings) -> None:

    @mcp.tool(annotations=READ)
    async def azure_list_resource_health_events(
        subscription_id: str,
        limit: Annotated[
            int | None, Field(description="Max results (default 50, max 200).")
        ] = None,
    ) -> str:
        """List current/recent Azure Service Health events for a subscription:
        service issues, planned maintenance, and health/security advisories.

        Returns each event's type, status, title, summary, and impact window.
        """
        size = cap(limit)

        async def handler(client: AzureClient) -> dict[str, Any]:
            data = await client.get(
                f"/subscriptions/{subscription_id}/providers/Microsoft.ResourceHealth/events",
                {"api-version": API_VERSION},
            )
            rows = data.get("value", []) if isinstance(data, dict) else []
            items = [_project(e) for e in rows]
            return page(items, size, data.get("nextLink") if isinstance(data, dict) else None)

        return await run(
            "azure_list_resource_health_events",
            settings,
            handler,
            subscription_id=subscription_id,
        )
