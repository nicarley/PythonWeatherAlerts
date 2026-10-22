"""Portable identity, expiry, and priority rules for normalized NWS alerts."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


SEMANTIC_FIELDS = (
    "id", "title", "event", "headline", "summary", "description", "instruction",
    "severity", "urgency", "certainty", "category", "response", "status",
    "message_type", "sent", "updated", "effective", "onset", "ends", "expires",
    "area_desc", "area_description", "geometry", "geocode", "affected_zones",
    "parameters", "references", "link",
)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value) if value.is_integer() else value
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def alert_revision(alert: Mapping[str, Any]) -> str:
    """Hash semantic fields, excluding location-specific distance and UI/rule flags.

    Cross-platform contract: UTF-8 JSON, sorted keys, compact separators,
    literal Unicode, missing fields represented as null, integral floats as
    integers. Array order is preserved, including geometry rings.
    """
    semantic = {field: _canonical_value(alert.get(field)) for field in SEMANTIC_FIELDS}
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def expiry_timestamp(alert: Mapping[str, Any]) -> Optional[float]:
    """Return the earliest valid expires/ends instant, or None if neither exists.

    Offset timestamps are converted to UTC; legacy timestamps without an offset
    are treated as UTC consistently across machines. Numeric values are Unix
    seconds. This does not infer expiry when the upstream data lacks it.
    """
    instants = []
    for field in ("expires", "ends"):
        value = alert.get(field)
        if value is None or value == "" or isinstance(value, bool):
            continue
        try:
            if isinstance(value, (int, float)):
                timestamp = float(value)
            else:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                timestamp = parsed.timestamp()
            if math.isfinite(timestamp):
                instants.append(timestamp)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
    return min(instants) if instants else None


def is_cancelled(alert: Mapping[str, Any]) -> bool:
    return str(alert.get("message_type") or alert.get("messageType") or "").casefold() == "cancel"


def alert_priority_key(alert: Mapping[str, Any]) -> tuple:
    """Ascending sort key: hazard severity, urgency, certainty, distance, ID."""
    severity = {"unknown": 0, "minor": 1, "moderate": 2, "severe": 3, "extreme": 4}
    urgency = {"unknown": 0, "past": 0, "future": 1, "expected": 2, "immediate": 3}
    certainty = {"unknown": 0, "unlikely": 0, "possible": 1, "likely": 2, "observed": 3}
    distance = alert.get("distance_miles")
    if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance):
        distance = math.inf
    return (
        -severity.get(str(alert.get("severity") or "unknown").casefold(), 0),
        -urgency.get(str(alert.get("urgency") or "unknown").casefold(), 0),
        -certainty.get(str(alert.get("certainty") or "unknown").casefold(), 0),
        float(distance),
        str(alert.get("id") or ""),
    )


def active_unexpired_alerts(alerts, now: Optional[float] = None) -> list[dict[str, Any]]:
    """Copy active alerts whose declared validity has not ended at now.

    Missing/invalid expiry is not evidence that an alert ended. This helper
    filters explicit cancellation notices but does not infer an all-clear from
    an expired cache; the caller must track the source's retrieval state.
    """
    import time

    instant = time.time() if now is None else float(now)
    if not math.isfinite(instant):
        raise ValueError("now must be a finite Unix timestamp")
    result = []
    for alert in alerts:
        if not isinstance(alert, Mapping) or is_cancelled(alert):
            continue
        expires = expiry_timestamp(alert)
        if expires is None or expires > instant:
            result.append(dict(alert))
    return result
