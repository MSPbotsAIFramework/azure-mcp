# azure-mcp

Azure Resource Manager MCP server -- exposes a customer's Microsoft Azure cloud estate
(subscriptions, resource inventory, Azure Advisor recommendations, Azure Resource Health /
Service Health events, and Azure Monitor metrics) as MCP tools over Streamable HTTP. This is a
distinct scope from Microsoft Graph (Entra ID users/mail/Teams -- see `ms-graph-mcp`) and from
M365 GDAP tenant management (see `gdap-mcp`): subscriptions, resources, Advisor, Resource
Health, and Monitor all live under a customer's own Azure AD app registration and RBAC grant
against `management.azure.com`, independent of any Graph/GDAP consent.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Quick Start

### Docker (recommended)

```bash
docker compose up --build
```

The server starts on `http://localhost:8080`.

### Local (uv)

```bash
uv sync
python -m azure_mcp
```

## Health Check

```bash
curl http://localhost:8080/health
# {"status": "ok"}
```

No credentials are required for the health endpoint.

## Authentication headers

Every request to `/mcp` must include all three headers below, naming an Azure AD (Entra ID)
app registration with client-credentials access:

| Header | Required | Meaning | Where to get it |
|---|---|---|---|
| `X-Azure-Tenant-Id` | yes | Azure AD tenant (directory) id the app registration lives in | Azure Portal -> Microsoft Entra ID -> Overview -> Tenant ID |
| `X-Azure-Client-Id` | yes | App registration (service principal) client id | Azure Portal -> Microsoft Entra ID -> App registrations -> your app -> Application (client) ID |
| `X-Azure-Client-Secret` | yes | App registration client secret | Azure Portal -> your app registration -> Certificates & secrets -> New client secret |

**Prerequisite (customer/Azure side, not automated by this server):** the app registration must
be granted at least the **Reader** role (Access control (IAM) -> Add role assignment -> Reader)
on every subscription it should be able to see. Without it, every tool against that subscription
returns a structured `unauthorized` error -- this is expected, not a server defect.

Missing any of the three headers returns `401` and lists which ones are missing, without calling
Azure. Azure AD rejecting the credentials, or Azure accepting them but the app registration
lacking the Reader role, both return a structured `unauthorized` tool error (never a 500).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCP_HTTP_PORT` | `8080` | Listening port |
| `MCP_HTTP_HOST` | `0.0.0.0` | Listening host |
| `AZURE_AD_BASE_URL` | `https://login.microsoftonline.com` | Override for sovereign clouds (not used in v1) |
| `AZURE_ARM_BASE_URL` | `https://management.azure.com` | Override for sovereign clouds (not used in v1) |

## MCP Endpoint

```
POST http://localhost:8080/mcp
```

Connect your MCP client with:
- Transport: Streamable HTTP
- Headers: `X-Azure-Tenant-Id`, `X-Azure-Client-Id`, `X-Azure-Client-Secret`

## Tools

All tools are read-only.

| Tool | Description |
|---|---|
| `azure_list_subscriptions` | List the Azure subscriptions visible to the credentialed app registration. |
| `azure_get_subscription` | Get one subscription's id, displayName, state and tenantId. |
| `azure_list_resources` | List resources in a subscription, optionally filtered by resource group and/or type. |
| `azure_list_advisor_recommendations` | List Azure Advisor recommendations for a subscription, optionally filtered by category. |
| `azure_list_resource_health_events` | List Service Health events (issues, planned maintenance, advisories) for a subscription. |
| `azure_list_resource_metric_definitions` | List the Azure Monitor metric names available for one ARM resource. |
| `azure_get_resource_metrics` | Get Azure Monitor time-series values for one or more metrics on a resource. |

Typical flow: `azure_list_subscriptions` -> pick a `subscriptionId` -> `azure_get_subscription` /
`azure_list_resources` / `azure_list_advisor_recommendations` /
`azure_list_resource_health_events`. For metrics on a specific resource:
`azure_list_resources` -> pick a resource's `id` -> `azure_list_resource_metric_definitions`
(discover metric names, never guess them) -> `azure_get_resource_metrics`.

## Non-goals (v1)

- No write/mutate tools -- this connector is read-only.
- No Azure Government / China 21Vianet / Germany sovereign-cloud support (the base-URL
  environment variables above are a hook for this, unused today).
- No Azure Monitor Activity Log (subscription-wide audit trail) -- a distinct ARM endpoint from
  the Resource Health / Monitor-metrics surfaces covered here.
- No Log Analytics / KQL query execution.

## License

Apache-2.0. Copyright 2026 MSPbots.ai.
