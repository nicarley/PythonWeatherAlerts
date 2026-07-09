from datetime import datetime
from typing import Any, Dict, List, Optional

from .rules import SEVERITY_ORDER


def default_escalation_rules() -> Dict[str, Any]:
    return {
        "enabled": True,
        "min_severity": "Severe",
        "radius_miles": 40,
        "repeat_minutes": 5,
        "force_all_channels": True,
        "keywords": ["tornado warning", "flash flood warning", "severe thunderstorm warning"],
    }


def evaluate_escalation(
    alert: Dict[str, Any],
    location_rules: Dict[str, Any],
    distance_miles: Optional[float],
    now: datetime,
) -> Dict[str, Any]:
    cfg = default_escalation_rules()
    cfg.update(location_rules.get("escalation", {}))
    if not cfg.get("enabled", True):
        return {"escalate": False, "reasons": []}

    reasons: List[str] = []
    min_severity = cfg.get("min_severity", "Severe")
    severity = alert.get("severity", "Unknown")
    severity_matches = SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(min_severity, 3)
    if severity_matches:
        reasons.append(f"severity>={min_severity}")

    radius_miles = float(cfg.get("radius_miles", 40))
    within_radius = distance_miles is None
    if distance_miles is not None:
        within_radius = distance_miles <= radius_miles
        if within_radius:
            reasons.append(f"within {radius_miles:.0f}mi")

    keyword_text = f"{alert.get('title', '')} {alert.get('event', '')}".lower()
    keyword_matches = False
    for keyword in cfg.get("keywords", []):
        if keyword.lower() in keyword_text:
            keyword_matches = True
            reasons.append(f"keyword:{keyword}")
            break

    # Escalation is a threat threshold constrained by proximity. Keywords may
    # promote a matching alert to that threshold, but proximity still applies
    # whenever alert geometry is available.
    escalate = bool((severity_matches or keyword_matches) and within_radius)
    return {
        "escalate": escalate,
        "reasons": reasons,
        "override_quiet_hours": escalate,
        "repeat_minutes": int(cfg.get("repeat_minutes", 5)),
        "force_all_channels": bool(cfg.get("force_all_channels", True)),
        "evaluated_at": now.isoformat(timespec="seconds"),
    }
