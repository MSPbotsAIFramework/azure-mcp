# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Azure Advisor recommendations for a subscription (AC4)."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import AzureClient
from ..settings import Settings
from ._common import READ, cap, odata_quote, page, run

API_VERSION = "2023-01-01"

Category = Literal["Cost", "Security", "HighAvailability", "Performance", "OperationalExcellence"]


def _project(rec: dict[str, Any]) -> dict[str, Any]:
    props = rec.get("properties") or {}
    short = props.get("shortDescription") or {}
    resource_metadata = props.get("resourceMetadata") or {}
    return {
        "id": rec.get("id"),
        "category": props.get("category"),
        "impact": props.get("impact"),
        "impactedField": props.get("impactedField"),
        "problem": short.get("problem"),
        "solution": short.get("solution"),
        "resourceId": resource_metadata.get("resourceId"),
    }


def register(mcp: FastMCP, settings: Settings) -> None:

    @mcp.tool(annotations=READ)
    async def azure_list_advisor_recommendations(
        subscription_id: str,
        category: Annotated[
            Category | None,
            Field(description="Filter to one Advisor category. Omit for all categories."),
        ] = None,
        limit: Annotated[
            int | None, Field(description="Max results (default 50, max 200).")
        ] = None,
    ) -> str:
        """List Azure Advisor recommendations for a subscription.

        Returns each recommendation's category, impact, the affected field,
        a problem/solution summary, and the ARM resourceId it applies to.
        """
        size = cap(limit)

        async def handler(client: AzureClient) -> dict[str, Any]:
            params = {"api-version": API_VERSION}
            if category:
                params["$filter"] = f"Category eq '{odata_quote(category)}'"
            data = await client.get(
                f"/subscriptions/{subscription_id}/providers/Microsoft.Advisor/recommendations",
                params,
            )
            rows = data.get("value", []) if isinstance(data, dict) else []
            items = [_project(r) for r in rows]
            return page(items, size, data.get("nextLink") if isinstance(data, dict) else None)

        return await run(settings, handler)
