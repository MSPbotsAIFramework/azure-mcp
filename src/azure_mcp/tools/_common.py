# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Shared plumbing for tool handlers: uniform error handling, pagination
defaults, and tool-semantic annotations (SOP section 2.6).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.types import ToolAnnotations

from .._json import dump_json_capped
from ..auth import current
from ..client import AzureClient
from ..errors import AzureApiError, error_envelope
from ..settings import CLIENT_ID_HEADER, CLIENT_SECRET_HEADER, TENANT_HEADER, Settings

log = logging.getLogger("azure_mcp")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

NO_CREDENTIALS = (
    f"No Azure credentials for this request. Send {TENANT_HEADER}, {CLIENT_ID_HEADER} and "
    f"{CLIENT_SECRET_HEADER}."
)


def cap(limit: int | None, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    return min(max(int(limit or default), 1), maximum)


Handler = Callable[[AzureClient], Awaitable[Any]]


async def run(settings: Settings, handler: Handler) -> str:
    """Execute ``handler`` with an AzureClient bound to this request's
    credentials. Always returns a string: the JSON result, or an error
    envelope -- tools never raise (SOP section 4.1).
    """
    creds = current()
    if creds is None:
        return error_envelope("not_configured", NO_CREDENTIALS)
    try:
        async with AzureClient(creds, settings) as client:
            result = await handler(client)
    except AzureApiError as exc:
        return exc.to_envelope()
    except ToolInputError as exc:
        return error_envelope("invalid_argument", str(exc))
    except Exception:  # noqa: BLE001 - tools must never raise
        log.exception("unexpected error in tool handler")
        return error_envelope("upstream_error", "Unexpected error while calling Azure.", True)
    return result if isinstance(result, str) else dump_json_capped(result)


class ToolInputError(ValueError):
    """Raised by handlers for arguments Azure would reject anyway, so the
    tool layer maps them to ``invalid_argument`` without a round trip.
    """


def odata_quote(value: str) -> str:
    """Escape a value for use inside a single-quoted OData $filter literal.

    OData escapes a quote by doubling it; without this, a value containing an
    apostrophe would close the literal early and Azure would reject (or
    misparse) the whole $filter.
    """
    return value.replace("'", "''")


def page(items: list, limit: int, next_link: str | None = None) -> dict[str, Any]:
    """Slice a fully-fetched ARM list response to ``limit`` items.

    v1 does not chase ARM's $skiptoken across pages (design doc Data & API
    contract: "the server stores no cursor state"), so this always returns
    the first ``limit`` items of what ARM returned for this call and sets
    has_more when either the result was sliced or ARM itself reported a
    nextLink (meaning there is more beyond what was fetched).
    """
    truncated = len(items) > limit
    sliced = items[:limit]
    return {
        "items": sliced,
        "count": len(sliced),
        "limit": limit,
        "has_more": truncated or bool(next_link),
    }


def resource_id_path(resource_id: str) -> str:
    """Validate and normalize a caller-supplied ARM resource id into the
    path segment used by client.get(). A full ARM resource id always starts
    with ``/subscriptions/...``; anything else is a caller mistake, not an
    Azure-side failure, so it is rejected locally as invalid_argument rather
    than sent to Azure.
    """
    value = (resource_id or "").strip()
    if not value.startswith("/subscriptions/"):
        raise ToolInputError(
            f"resource_id must be a full ARM resource id starting with "
            f"/subscriptions/, got {value!r}."
        )
    return value
