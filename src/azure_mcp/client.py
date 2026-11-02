# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Thin async client for Azure AD (Entra ID) token exchange and the Azure
Resource Manager (ARM) REST API.

Reference (public, no login required):
- Azure AD v2 client-credentials token: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow
- ARM subscriptions: https://learn.microsoft.com/en-us/rest/api/resources/subscriptions
- ARM resources: https://learn.microsoft.com/en-us/rest/api/resources/resources
- Azure Advisor: https://learn.microsoft.com/en-us/rest/api/advisor/
- Azure Resource Health: https://learn.microsoft.com/en-us/rest/api/resourcehealth/
- Azure Monitor metrics: https://learn.microsoft.com/en-us/rest/api/monitor/metrics/

A token is fetched fresh for every tool call and never cached across requests
or tenants (design doc Non-functional: correctness over shaving one round
trip -- this is the explicit, deliberate trade-off that keeps the service
stateless and multi-tenant-safe, SOP section 3.3/3.4).
"""

import asyncio
import time
from typing import Any

import httpx

from .auth import Credentials
from .errors import AzureApiError, status_to_code
from .settings import Settings

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_BACKOFF = 20.0
USER_AGENT = "mspbots-azure-mcp/1.0"


def _retry_after(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("retry-after")
    if value:
        try:
            return min(float(value), MAX_BACKOFF)
        except ValueError:
            pass
    return min(2.0**attempt, MAX_BACKOFF)


def _error_detail(response: httpx.Response) -> str:
    """Azure's own explanation, from a JSON or plain-text error body.

    ARM errors are typically ``{"error": {"code": "...", "message": "..."}}``;
    Azure AD token errors are ``{"error": "...", "error_description": "..."}``.
    Either way this is what names the bad metric/parameter for AC7/AC10.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:500]
    if isinstance(body, dict):
        inner = body.get("error")
        if isinstance(inner, dict):
            msg = inner.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()[:500]
        for key in ("error_description", "message"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
        if isinstance(inner, str) and inner.strip():
            return inner.strip()[:500]
    return str(body)[:500]


class AzureClient:
    """One instance per tool call; wraps a single httpx client and exchanges
    exactly one access token for that call (never persisted beyond it).
    """

    def __init__(
        self,
        creds: Credentials,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._settings = settings
        self._creds = creds
        self._token: str | None = None
        self._deadline = time.monotonic() + settings.call_budget_seconds
        self._http = httpx.AsyncClient(
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
            transport=transport,
        )

    async def __aenter__(self) -> "AzureClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send with bounded retry on 429/5xx/timeouts, honouring Retry-After
        and the per-call time budget (<120s, design doc / SOP section 5).
        All ARM calls here are read-only GETs, so every retry is safe to repeat.
        """
        attempt = 0
        while True:
            try:
                response = await self._http.request(method, url, **kwargs)
            except httpx.TimeoutException as exc:
                if attempt < self._settings.max_retries and time.monotonic() + 1 < self._deadline:
                    attempt += 1
                    await asyncio.sleep(min(2.0**attempt, MAX_BACKOFF))
                    continue
                raise AzureApiError(
                    "upstream_error", "Azure did not respond in time.", True
                ) from exc
            except httpx.HTTPError as exc:
                raise AzureApiError(
                    "upstream_error", f"Could not reach Azure: {type(exc).__name__}.", True
                ) from exc

            if response.status_code in RETRY_STATUSES and attempt < self._settings.max_retries:
                wait = _retry_after(response, attempt + 1)
                if time.monotonic() + wait < self._deadline:
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
            return response

    async def token(self) -> str:
        if self._token:
            return self._token
        token_url = f"{self._settings.azure_ad_base_url}/{self._creds.tenant_id}/oauth2/v2.0/token"
        response = await self._send(
            "POST",
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._creds.client_id,
                "client_secret": self._creds.client_secret,
                "scope": f"{self._settings.azure_arm_base_url}/.default",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code in (400, 401):
            # Azure AD's AADSTS* errors for bad tenant/client/secret all land
            # here -- never a 500 (AC9).
            raise AzureApiError(
                "unauthorized",
                f"Azure AD rejected the tenant/client credentials ({response.status_code}). "
                f"{_error_detail(response)}".strip(),
                False,
                response.status_code,
            )
        if response.status_code >= 400:
            code, retryable = status_to_code(response.status_code)
            raise AzureApiError(code, _error_detail(response), retryable, response.status_code)
        try:
            token = response.json().get("access_token")
        except (ValueError, AttributeError):
            token = None
        if not token:
            raise AzureApiError(
                "upstream_error", "Azure AD token response had no access_token.", True
            )
        self._token = token
        return token

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET an ARM path (absolute, starting with ``/``) with the bearer
        token attached. ``path`` may itself be a full ``resource_id`` (also
        starts with ``/``), so no base-URL rewriting is needed beyond
        prefixing the ARM host.
        """
        token = await self.token()
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        url = f"{self._settings.azure_arm_base_url}{path}"
        response = await self._send(
            "GET", url, params=clean, headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code >= 400:
            code, retryable = status_to_code(response.status_code)
            raise AzureApiError(code, _error_detail(response), retryable, response.status_code)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise AzureApiError(
                "upstream_error", "Azure returned a response that is not JSON.", True
            ) from exc
