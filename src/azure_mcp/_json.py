# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Token-economical JSON serialization for tool return values.

Compact (no indent), non-ASCII-preserving, and size-capped so a single tool
call can never exceed the ~20,000-char budget an Agent's context can
reasonably absorb (SOP section 2.5).
"""

from typing import Any

from .errors import compact

MAX_CHARS = 20_000


def dump_json_capped(data: Any, max_chars: int = MAX_CHARS) -> str:
    """Serialize ``data`` compactly, truncating the largest list field (or the
    top-level list) if the result would exceed ``max_chars``, rather than ever
    returning an unbounded blob.
    """
    s = compact(data)
    if len(s) <= max_chars:
        return s

    if isinstance(data, list):
        return _truncate_list(data, max_chars, wrap_key="items")

    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if list_keys:
            key = max(list_keys, key=lambda k: len(compact(data[k])))
            items = data[key]
            lo, hi = 0, len(items)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                candidate = dict(data)
                candidate[key] = items[:mid]
                candidate["truncated"] = True
                candidate["truncated_field"] = key
                candidate["original_count"] = len(items)
                candidate["has_more"] = True
                if len(compact(candidate)) <= max_chars:
                    lo = mid
                else:
                    hi = mid - 1
            candidate = dict(data)
            candidate[key] = items[:lo]
            candidate["truncated"] = True
            candidate["truncated_field"] = key
            candidate["original_count"] = len(items)
            candidate["has_more"] = True
            return compact(candidate)

    return compact(
        {
            "truncated": True,
            "note": f"Result too large ({len(s)} chars), not list-shaped; narrow your query.",
        }
    )


def _truncate_list(items: list, max_chars: int, wrap_key: str) -> str:
    lo, hi = 0, len(items)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = {
            wrap_key: items[:mid],
            "truncated": True,
            "original_count": len(items),
            "has_more": True,
        }
        if len(compact(candidate)) <= max_chars:
            lo = mid
        else:
            hi = mid - 1
    return compact(
        {wrap_key: items[:lo], "truncated": True, "original_count": len(items), "has_more": True}
    )
