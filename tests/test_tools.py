# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Tool behaviour against a mocked Azure AD + ARM API (TC1-TC13), plus the
tools/list snapshot (SOP section 13: a signature change here is deliberately
visible as a red test, not a silent diff).
"""

import httpx
import pytest
from conftest import ARM_BASE, TOKEN_URL

pytestmark = pytest.mark.usefixtures("creds")

EXPECTED_TOOLS = {
    "azure_list_subscriptions": set(),
    "azure_get_subscription": {"subscription_id"},
    "azure_list_resources": {"subscription_id"},
    "azure_list_advisor_recommendations": {"subscription_id"},
    "azure_list_resource_health_events": {"subscription_id"},
    "azure_list_resource_metric_definitions": {"resource_id"},
    "azure_get_resource_metrics": {"resource_id", "metric_names", "timespan"},
}


async def _tools(mcp):
    return {t.name: t for t in await mcp.list_tools()}


# ---- tools/list snapshot -----------------------------------------------------


async def test_tool_names_match_design(mcp):
    assert set(await _tools(mcp)) == set(EXPECTED_TOOLS)


async def test_required_parameters_match_design(mcp):
    tools = await _tools(mcp)
    for name, required in EXPECTED_TOOLS.items():
        assert set(tools[name].inputSchema.get("required", [])) == required, name


async def test_descriptions_are_concise(mcp):
    for tool in (await _tools(mcp)).values():
        assert tool.description and len(tool.description) <= 500, tool.name
        assert len(tool.description.splitlines()[0]) <= 100, tool.name


async def test_all_tools_are_read_only(mcp):
    for tool in (await _tools(mcp)).values():
        assert tool.annotations.readOnlyHint is True, tool.name
        assert tool.annotations.destructiveHint is False, tool.name


async def test_tool_names_have_azure_prefix(mcp):
    for name in await _tools(mcp):
        assert name.startswith("azure_"), name


# ---- token exchange shared by every tool (AC9) -------------------------------


@pytest.fixture(autouse=True)
def token_route(respx_mock):
    return respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
    )


def _form(route):
    from urllib.parse import parse_qs

    return parse_qs(route.calls.last.request.content.decode())


async def test_token_request_uses_client_credentials_grant(respx_mock, call, token_route):
    respx_mock.get(f"{ARM_BASE}/subscriptions").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    await call("azure_list_subscriptions")
    form = _form(token_route)
    assert form["grant_type"] == ["client_credentials"]
    assert form["client_id"] == ["test-client-id"]
    assert form["client_secret"] == ["test-client-secret"]
    assert form["scope"] == [f"{ARM_BASE}/.default"]


async def test_token_is_fetched_fresh_per_call(respx_mock, call, token_route):
    respx_mock.get(f"{ARM_BASE}/subscriptions").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    await call("azure_list_subscriptions")
    await call("azure_list_subscriptions")
    assert token_route.call_count == 2  # never cached across requests (AC11)


# ---- TC1: list subscriptions --------------------------------------------------


async def test_list_subscriptions_returns_id_name_state(respx_mock, call):
    respx_mock.get(f"{ARM_BASE}/subscriptions").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "/subscriptions/sub-1",
                        "subscriptionId": "sub-1",
                        "displayName": "Prod",
                        "state": "Enabled",
                        "tenantId": "tenant-1",
                    }
                ]
            },
        )
    )
    out = await call("azure_list_subscriptions")
    assert out["items"] == [
        {
            "id": "/subscriptions/sub-1",
            "subscriptionId": "sub-1",
            "displayName": "Prod",
            "state": "Enabled",
            "tenantId": "tenant-1",
        }
    ]
    assert out["has_more"] is False


# ---- TC2/TC3: get subscription -------------------------------------------------


async def test_get_subscription_returns_details(respx_mock, call):
    respx_mock.get(f"{ARM_BASE}/subscriptions/sub-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "/subscriptions/sub-1",
                "subscriptionId": "sub-1",
                "displayName": "Prod",
                "state": "Enabled",
                "tenantId": "tenant-1",
            },
        )
    )
    out = await call("azure_get_subscription", subscription_id="sub-1")
    assert out["subscriptionId"] == "sub-1"
    assert out["displayName"] == "Prod"
    assert out["state"] == "Enabled"
    assert out["tenantId"] == "tenant-1"


async def test_get_subscription_unknown_is_not_found(respx_mock, call):
    respx_mock.get(f"{ARM_BASE}/subscriptions/unknown-sub").mock(
        return_value=httpx.Response(
            404, json={"error": {"code": "SubscriptionNotFound", "message": "nope"}}
        )
    )
    out = await call("azure_get_subscription", subscription_id="unknown-sub")
    assert out["error"]["code"] == "not_found"
    assert "unknown-sub" in out["error"]["message"]
    assert out["error"]["retryable"] is False


# ---- TC4/TC5: list resources ---------------------------------------------------


async def test_list_resources_default_pagination(respx_mock, call):
    vm_id = (
        "/subscriptions/sub-1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
    )
    next_link = "https://management.azure.com/subscriptions/sub-1/resources?$skiptoken=abc"
    route = respx_mock.get(f"{ARM_BASE}/subscriptions/sub-1/resources").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": vm_id,
                        "name": "vm1",
                        "type": "Microsoft.Compute/virtualMachines",
                        "location": "eastus",
                    }
                ],
                "nextLink": next_link,
            },
        )
    )
    out = await call("azure_list_resources", subscription_id="sub-1")
    assert route.calls.last.request.url.params["$top"] == "50"
    assert out["items"][0]["name"] == "vm1"
    assert out["items"][0]["resourceGroup"] == "rg1"
    assert out["has_more"] is True


async def test_list_resources_applies_filters(respx_mock, call):
    route = respx_mock.get(f"{ARM_BASE}/subscriptions/sub-1/resources").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    await call(
        "azure_list_resources",
        subscription_id="sub-1",
        resource_group="rg1",
        resource_type="Microsoft.Compute/virtualMachines",
    )
    filt = route.calls.last.request.url.params["$filter"]
    assert "resourceGroup eq 'rg1'" in filt
    assert "resourceType eq 'Microsoft.Compute/virtualMachines'" in filt
    assert " and " in filt


# ---- TC6: advisor recommendations ---------------------------------------------


async def test_advisor_recommendations_category_filter(respx_mock, call):
    route = respx_mock.get(
        f"{ARM_BASE}/subscriptions/sub-1/providers/Microsoft.Advisor/recommendations"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "rec-1",
                        "properties": {
                            "category": "Cost",
                            "impact": "High",
                            "impactedField": "Microsoft.Compute/virtualMachines",
                            "shortDescription": {
                                "problem": "Idle VM",
                                "solution": "Resize or deallocate",
                            },
                            "resourceMetadata": {"resourceId": "/subscriptions/sub-1/.../vm1"},
                        },
                    }
                ]
            },
        )
    )
    out = await call("azure_list_advisor_recommendations", subscription_id="sub-1", category="Cost")
    assert route.calls.last.request.url.params["$filter"] == "Category eq 'Cost'"
    assert out["items"][0]["category"] == "Cost"
    assert out["items"][0]["problem"] == "Idle VM"
    assert out["items"][0]["solution"] == "Resize or deallocate"


# ---- TC7: resource health events ----------------------------------------------


async def test_resource_health_events_list(respx_mock, call):
    respx_mock.get(
        f"{ARM_BASE}/subscriptions/sub-1/providers/Microsoft.ResourceHealth/events"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "event-1",
                        "properties": {
                            "eventType": "ServiceIssue",
                            "status": "Active",
                            "title": "Networking issue",
                            "summary": "Some VMs may be unreachable",
                            "impactStartTime": "2026-01-01T00:00:00Z",
                        },
                    }
                ]
            },
        )
    )
    out = await call("azure_list_resource_health_events", subscription_id="sub-1")
    assert out["items"][0]["eventType"] == "ServiceIssue"
    assert out["items"][0]["status"] == "Active"
    assert out["items"][0]["title"] == "Networking issue"


# ---- TC8: metric definitions ---------------------------------------------------


RESOURCE_ID = (
    "/subscriptions/sub-1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
)


async def test_metric_definitions_list(respx_mock, call):
    respx_mock.get(f"{ARM_BASE}{RESOURCE_ID}/providers/Microsoft.Insights/metricDefinitions").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "name": {"value": "Percentage CPU", "localizedValue": "Percentage CPU"},
                        "unit": "Percent",
                        "primaryAggregationType": "Average",
                    }
                ]
            },
        )
    )
    out = await call("azure_list_resource_metric_definitions", resource_id=RESOURCE_ID)
    assert out["items"][0]["name"] == "Percentage CPU"
    assert out["items"][0]["unit"] == "Percent"


async def test_metric_definitions_rejects_non_arm_resource_id(call):
    out = await call("azure_list_resource_metric_definitions", resource_id="not-an-arm-id")
    assert out["error"]["code"] == "invalid_argument"


# ---- TC9/TC10: metric values ----------------------------------------------------


async def test_get_resource_metrics_returns_series(respx_mock, call):
    respx_mock.get(f"{ARM_BASE}{RESOURCE_ID}/providers/Microsoft.Insights/metrics").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "name": {"value": "Percentage CPU"},
                        "unit": "Percent",
                        "timeseries": [
                            {
                                "data": [
                                    {"timeStamp": "2026-01-01T00:00:00Z", "average": 12.5},
                                    {"timeStamp": "2026-01-01T00:05:00Z", "average": 15.0},
                                ]
                            }
                        ],
                    }
                ]
            },
        )
    )
    out = await call(
        "azure_get_resource_metrics",
        resource_id=RESOURCE_ID,
        metric_names=["Percentage CPU"],
        timespan="2026-01-01T00:00:00Z/2026-01-01T01:00:00Z",
    )
    assert out["items"][0]["name"] == "Percentage CPU"
    assert out["items"][0]["data"] == [
        {"timestamp": "2026-01-01T00:00:00Z", "average": 12.5},
        {"timestamp": "2026-01-01T00:05:00Z", "average": 15.0},
    ]


async def test_get_resource_metrics_invalid_metric_name(respx_mock, call):
    respx_mock.get(f"{ARM_BASE}{RESOURCE_ID}/providers/Microsoft.Insights/metrics").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "code": "InvalidParameter",
                    "message": "Metric 'BogusMetric' is not supported",
                }
            },
        )
    )
    out = await call(
        "azure_get_resource_metrics",
        resource_id=RESOURCE_ID,
        metric_names=["BogusMetric"],
        timespan="2026-01-01T00:00:00Z/2026-01-01T01:00:00Z",
    )
    assert out["error"]["code"] == "invalid_argument"
    assert "BogusMetric" in out["error"]["message"]


# ---- TC12: unauthorized (bad credentials, missing RBAC) ------------------------


async def test_bad_credentials_token_exchange_is_unauthorized(respx_mock, call, token_route):
    token_route.mock(
        return_value=httpx.Response(
            401, json={"error": "invalid_client", "error_description": "AADSTS7000215"}
        )
    )
    out = await call("azure_list_subscriptions")
    assert out["error"]["code"] == "unauthorized"
    assert out["error"]["retryable"] is False


async def test_arm_403_missing_rbac_is_unauthorized(respx_mock, call):
    respx_mock.get(f"{ARM_BASE}/subscriptions/sub-1").mock(
        return_value=httpx.Response(
            403, json={"error": {"code": "AuthorizationFailed", "message": "no Reader role"}}
        )
    )
    out = await call("azure_get_subscription", subscription_id="sub-1")
    assert out["error"]["code"] == "unauthorized"


# ---- TC13: rate limiting --------------------------------------------------------


async def test_429_retries_then_succeeds(respx_mock, call):
    route = respx_mock.get(f"{ARM_BASE}/subscriptions")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"message": "slow down"}}),
        httpx.Response(200, json={"value": []}),
    ]
    out = await call("azure_list_subscriptions")
    assert out["items"] == []
    assert route.call_count == 2


async def test_429_exhausted_is_rate_limited(respx_mock, call, settings):
    route = respx_mock.get(f"{ARM_BASE}/subscriptions").mock(
        return_value=httpx.Response(
            429, headers={"Retry-After": "0"}, json={"error": {"message": "slow down"}}
        )
    )
    out = await call("azure_list_subscriptions")
    assert out["error"]["code"] == "rate_limited"
    assert out["error"]["retryable"] is True
    assert route.call_count == settings.max_retries + 1


# ---- missing credentials (defence in depth below the HTTP middleware) ---------


async def test_missing_credentials_envelope(call):
    from azure_mcp import auth

    token = auth._current.set(None)
    try:
        out = await call("azure_list_subscriptions")
    finally:
        auth._current.reset(token)
    assert out["error"]["code"] == "not_configured"
