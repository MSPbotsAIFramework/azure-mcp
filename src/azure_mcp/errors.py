# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Structured error envelope and the Azure/ARM HTTP-status -> code mapping.

Tools never raise: every error path returns ``{"error": {...}}`` as a string
so the Agent can branch on ``code`` and ``retryable`` (SOP section 4.2).
"""

import json
from dataclasses import dataclass
from typing import Any

ERROR_CODES = {
    "not_configured",
    "unauthorized",
    "not_found",
    "invalid_argument",
    "rate_limited",
    "upstream_error",
}


def compact(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str)


def error_envelope(code: str, message: str, retryable: bool = False) -> str:
    assert code in ERROR_CODES, code
    return compact({"error": {"code": code, "message": message, "retryable": retryable}})


@dataclass
class AzureApiError(Exception):
    """Raised by client.py for any Azure AD / ARM failure; carries enough to
    build the error envelope without the tool layer re-deriving it.
    """

    code: str
    message: str
    retryable: bool = False
    status: int | None = None

    def __str__(self) -> str:
        return self.message

    def to_envelope(self) -> str:
        return error_envelope(self.code, self.message, self.retryable)


def status_to_code(status: int) -> tuple[str, bool]:
    """Map an ARM/Azure AD HTTP status to (code, retryable).

    401/403 -> unauthorized (bad credentials, or missing RBAC Reader role --
    ARM cannot distinguish the two from the status code alone, AC9).
    404 -> not_found. 400/422 -> invalid_argument. 429 -> rate_limited
    (retryable). Anything else >=500 -> upstream_error (retryable); any other
    4xx also invalid_argument (ARM's own validation rejected the request).
    """
    if status in (401, 403):
        return "unauthorized", False
    if status == 404:
        return "not_found", False
    if status == 429:
        return "rate_limited", True
    if status in (400, 422):
        return "invalid_argument", False
    if status >= 500:
        return "upstream_error", True
    return "invalid_argument", False
