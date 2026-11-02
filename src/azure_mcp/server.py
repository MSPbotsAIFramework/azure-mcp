# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""FastMCP server and HTTP app."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .auth import CredentialMiddleware
from .settings import Settings
from .tools import advisor, monitor, resource_health, resources, subscriptions

INSTRUCTIONS = (
    "Azure MCP queries a customer's Microsoft Azure cloud estate via the Azure "
    "Resource Manager (ARM) API -- subscriptions, resource inventory, Azure "
    "Advisor recommendations, Azure Resource Health / Service Health events, "
    "and Azure Monitor metrics. This is a distinct scope from Microsoft Graph "
    "(users/mail/Teams -- see the separate ms-graph-mcp service) and from M365 "
    "GDAP tenant management (see gdap-mcp). All tools are read-only. "
    "Typical flow: azure_list_subscriptions to find a subscriptionId, then "
    "azure_get_subscription / azure_list_resources / "
    "azure_list_advisor_recommendations / azure_list_resource_health_events "
    "against it. To read metrics for a specific resource: "
    "azure_list_resources -> pick a resource's id -> "
    "azure_list_resource_metric_definitions (discover metric names, never "
    "guess them) -> azure_get_resource_metrics."
)


def create_mcp(settings: Settings) -> FastMCP:
    mcp = FastMCP(
        name="azure-mcp",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        # The gateway forwards requests with its own Host header; DNS-rebinding
        # protection would reject them with 421 (SOP section 7).
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    for module in (subscriptions, resources, advisor, resource_health, monitor):
        module.register(mcp, settings)
    return mcp


def create_app(settings: Settings) -> Starlette:
    mcp = create_mcp(settings)
    mcp_app = mcp.streamable_http_app()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Mount() does not run a sub-app's lifespan; without forwarding it the
    # streamable-http session manager never starts and /mcp fails with "Task
    # group is not initialized" while /health still passes (SOP section 7).
    return Starlette(
        routes=[Route("/health", health), Mount("/", app=CredentialMiddleware(mcp_app))],
        lifespan=lambda app: mcp_app.router.lifespan_context(app),
    )
