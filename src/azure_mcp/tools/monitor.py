# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Azure Monitor metric discovery (AC6) and metric values (AC7) for one
ARM resource. Metric names are discovered, never guessed: call
azure_list_resource_metric_definitions before azure_get_resource_metrics.
"""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import AzureClient
from ..errors import AzureApiError
from ..settings import Settings
from ._common import READ, resource_id_path, run

API_VERSION = "2024-02-01"


def _project_definition(d: dict[str, Any]) -> dict[str, Any]:
    name = d.get("name") or {}
    return {
        "name": name.get("value"),
        "displayName": name.get("localizedValue"),
        "unit": d.get("unit"),
        "primaryAggregationType": d.get("primaryAggregationType"),
    }


_AGG_FIELDS = ("average", "total", "count", "minimum", "maximum")


def _project_data_point(point: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"timestamp": point.get("timeStamp")}
    for field in _AGG_FIELDS:
        if point.get(field) is not None:
            out[field] = point[field]
    return out


def _project_metric(metric: dict[str, Any]) -> dict[str, Any]:
    name = metric.get("name") or {}
    timeseries = metric.get("timeseries") or []
    data = timeseries[0].get("data", []) if timeseries else []
    return {
        "name": name.get("value"),
        "unit": metric.get("unit"),
        "data": [_project_data_point(p) for p in data],
    }


def register(mcp: FastMCP, settings: Settings) -> None:

    @mcp.tool(annotations=READ)
    async def azure_list_resource_metric_definitions(resource_id: str) -> str:
        """List the Azure Monitor metric names available for one ARM resource.

        resource_id is a full ARM resource id, typically taken from
        azure_list_resources' output. Use the returned metric names as the
        metric_names argument to azure_get_resource_metrics -- do not guess
        metric names.
        """

        async def handler(client: AzureClient) -> dict[str, Any]:
            path = resource_id_path(resource_id)
            data = await client.get(
                f"{path}/providers/Microsoft.Insights/metricDefinitions",
                {"api-version": API_VERSION},
            )
            rows = data.get("value", []) if isinstance(data, dict) else []
            items = [_project_definition(d) for d in rows]
            return {"items": items, "count": len(items)}

        return await run("azure_list_resource_metric_definitions", settings, handler)

    @mcp.tool(annotations=READ)
    async def azure_get_resource_metrics(
        resource_id: str,
        metric_names: Annotated[
            list[str],
            Field(
                description="One or more metric names from azure_list_resource_metric_definitions, "
                "e.g. ['Percentage CPU']."
            ),
        ],
        timespan: Annotated[
            str,
            Field(
                description="ISO 8601 interval to query, e.g. "
                "'2026-01-01T00:00:00Z/2026-01-01T01:00:00Z'."
            ),
        ],
        interval: Annotated[
            str | None,
            Field(
                description="ISO 8601 duration granularity, e.g. 'PT5M'. Omit for Azure's default."
            ),
        ] = None,
        aggregation: Annotated[
            str | None,
            Field(description="Aggregation type: Average, Total, Count, Minimum or Maximum."),
        ] = "Average",
    ) -> str:
        """Get Azure Monitor time-series values for one or more metrics on a resource.

        Returns a structured invalid_argument error naming the bad metric if
        any requested metric_names entry is unknown for this resource.
        """

        async def handler(client: AzureClient) -> dict[str, Any]:
            path = resource_id_path(resource_id)
            params: dict[str, Any] = {
                "api-version": API_VERSION,
                "metricnames": ",".join(metric_names),
                "timespan": timespan,
            }
            if interval:
                params["interval"] = interval
            if aggregation:
                params["aggregation"] = aggregation
            try:
                data = await client.get(f"{path}/providers/Microsoft.Insights/metrics", params)
            except AzureApiError as exc:
                if exc.code == "invalid_argument":
                    names = ", ".join(metric_names)
                    raise AzureApiError(
                        "invalid_argument",
                        f"Invalid metric name(s) requested: {names}. Azure said: {exc.message}",
                        False,
                        exc.status,
                    ) from exc
                raise
            rows = data.get("value", []) if isinstance(data, dict) else []
            items = [_project_metric(m) for m in rows]
            return {"items": items, "count": len(items)}

        return await run("azure_get_resource_metrics", settings, handler)
