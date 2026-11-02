# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Resource inventory within a subscription (AC3), including the supporting
discovery step azure_get_resource_metrics needs: finding a resource's ARM id.
"""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import AzureClient
from ..settings import Settings
from ._common import READ, cap, odata_quote, page, run

API_VERSION = "2021-04-01"


def _project(resource: dict[str, Any]) -> dict[str, Any]:
    rid = resource.get("id") or ""
    resource_group = None
    parts = rid.lower().split("/")
    if "resourcegroups" in parts:
        idx = parts.index("resourcegroups")
        if idx + 1 < len(parts):
            # Use the original-case segment, not the lowercased one used for matching.
            resource_group = rid.split("/")[idx + 1]
    return {
        "id": rid,
        "name": resource.get("name"),
        "type": resource.get("type"),
        "location": resource.get("location"),
        "resourceGroup": resource_group,
    }


def register(mcp: FastMCP, settings: Settings) -> None:

    @mcp.tool(annotations=READ)
    async def azure_list_resources(
        subscription_id: str,
        resource_group: Annotated[
            str | None, Field(description="Filter to resources in this resource group only.")
        ] = None,
        resource_type: Annotated[
            str | None,
            Field(description="ARM resource type filter, e.g. Microsoft.Compute/virtualMachines"),
        ] = None,
        limit: Annotated[
            int | None, Field(description="Max results (default 50, max 200).")
        ] = None,
    ) -> str:
        """List resources in a subscription, optionally filtered by resource group and/or type.

        Returns each resource's id, name, type, location and resourceGroup. A
        resource's id is the full ARM resource id other tools in this service
        (azure_list_resource_metric_definitions, azure_get_resource_metrics)
        take as their resource_id argument.
        """
        size = cap(limit)

        async def handler(client: AzureClient) -> dict[str, Any]:
            clauses = []
            if resource_group:
                clauses.append(f"resourceGroup eq '{odata_quote(resource_group)}'")
            if resource_type:
                clauses.append(f"resourceType eq '{odata_quote(resource_type)}'")
            params = {"api-version": API_VERSION, "$top": size}
            if clauses:
                params["$filter"] = " and ".join(clauses)
            data = await client.get(f"/subscriptions/{subscription_id}/resources", params)
            rows = data.get("value", []) if isinstance(data, dict) else []
            items = [_project(r) for r in rows]
            return page(items, size, data.get("nextLink") if isinstance(data, dict) else None)

        return await run(settings, handler)
