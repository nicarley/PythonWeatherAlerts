import copy
from datetime import datetime
from typing import Any, Dict, List, Tuple

from weather_alert.identity import SEMANTIC_FIELDS, alert_revision, is_cancelled

SEVERITY_ORDER = {"Unknown": 0, "Minor": 1, "Moderate": 2, "Severe": 3, "Extreme": 4}


def default_location_rules() -> Dict[str, Any]:
    return {
        "min_severity": "Minor",
        "types": ["warning", "watch", "advisory"],
        "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00"},
        "desktop_notifications": None,
        "play_sounds": None,
        "webhook_enabled": False,
        "suppression_cooldown_seconds": 900,
        "escalation": {
            "enabled": True,
            "min_severity": "Severe",
            "radius_miles": 40,
            "repeat_minutes": 5,
            "force_all_channels": True,
            "keywords": ["tornado warning", "flash flood warning", "severe thunderstorm warning"],
        },
        "audio_profiles": {
            "day": {"start": "07:00", "end": "22:00", "voice_rate": 200, "beep_count": 1},
            "night": {"start": "22:00", "end": "07:00", "voice_rate": 170, "beep_count": 1},
            "escalated": {"voice_rate": 215, "beep_count": 3},
        },
    }


def normalize_location_entry(location: Dict[str, Any]) -> Dict[str, Any]:
    normalized = copy.deepcopy(location)
    normalized.setdefault("name", "Unnamed")
    normalized.setdefault("id", "")
    normalized["group"] = str(normalized.get("group") or "Ungrouped").strip() or "Ungrouped"
    normalized["rules"] = _merge_rule_defaults(default_location_rules(), normalized.get("rules"))
    return normalized


def _merge_rule_defaults(defaults: Dict[str, Any], overrides: Any) -> Dict[str, Any]:
    """Keep nested defaults when older settings contain only some rule fields."""
    merged = copy.deepcopy(defaults)
    if not isinstance(overrides, dict):
        return merged
    for key, value in overrides.items():
        if isinstance(defaults.get(key), dict):
            merged[key] = _merge_rule_defaults(defaults[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def get_alert_type(alert_title: str, event: str = "") -> str:
    text = f"{alert_title} {event}".lower()
    if "warning" in text:
        return "warning"
    if "watch" in text:
        return "watch"
    if "advisory" in text:
        return "advisory"
    return "other"


def _is_quiet_hours(now: datetime, start: str, end: str) -> bool:
    now_mins = now.hour * 60 + now.minute
    try:
        s_h, s_m = [int(v) for v in start.split(":")]
        e_h, e_m = [int(v) for v in end.split(":")]
    except (ValueError, TypeError):
        return False
    start_mins = s_h * 60 + s_m
    end_mins = e_h * 60 + e_m

    if start_mins == end_mins:
        return False
    if start_mins < end_mins:
        return start_mins <= now_mins < end_mins
    return now_mins >= start_mins or now_mins < end_mins


def evaluate_location_rule(alert: Dict[str, Any], rules: Dict[str, Any], now: datetime, ignore_quiet_hours: bool = False) -> Tuple[bool, str]:
    min_severity = rules.get("min_severity", "Minor")
    current_severity = alert.get("severity", "Unknown")
    if SEVERITY_ORDER.get(current_severity, 0) < SEVERITY_ORDER.get(min_severity, 1):
        return False, f"below min severity ({min_severity})"

    allowed_types = set(rules.get("types", ["warning", "watch", "advisory"]))
    alert_type = get_alert_type(alert.get("title", ""), alert.get("event", ""))
    if alert_type not in allowed_types:
        return False, f"type {alert_type} not enabled"

    quiet_cfg = rules.get("quiet_hours", {})
    if quiet_cfg.get("enabled") and not ignore_quiet_hours:
        start = quiet_cfg.get("start", "22:00")
        end = quiet_cfg.get("end", "07:00")
        if _is_quiet_hours(now, start, end):
            return False, "quiet hours"

    return True, "allowed"


def _fingerprint(alert: Dict[str, Any]) -> str:
    return alert_revision(alert)

def summarize_lifecycle(previous_alerts: Dict[str, Dict[str, Any]], current_alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
    notices = [alert for alert in current_alerts if is_cancelled(alert)]
    known = {**previous_alerts, **{a.get("id"): a for a in current_alerts if a.get("id") and not is_cancelled(a)}}
    cancelled_by_id = {}
    notice_ids = {a.get("id") for a in notices if a.get("id")}
    for notice in notices:
        targets = {notice["id"]} if notice.get("id") in known else set()
        for reference in notice.get("references") or []:
            if isinstance(reference, dict):
                candidates = [reference.get("identifier"), reference.get("id"), reference.get("@id")]
            elif isinstance(reference, str):
                candidates = [reference, *reference.split(",")[1:2]]
            else:
                candidates = []
            targets.update(candidate for candidate in candidates if isinstance(candidate, str) and candidate in known)
        if not targets and notice.get("id"):
            targets.add(notice["id"])
        for target in targets:
            cancelled_by_id[target] = {**known.get(target, notice), "id": target, "message_type": "Cancel", "cancellation_id": notice.get("id", "")}
    cancelled = [cancelled_by_id[key] for key in sorted(cancelled_by_id)]
    cancelled_ids = set(cancelled_by_id) | notice_ids
    current_by_id = {
        a["id"]: a for a in current_alerts
        if a.get("id") and a["id"] not in cancelled_ids and not is_cancelled(a)
    }
    previous_ids = set(previous_alerts.keys())
    current_ids = set(current_by_id.keys())

    new_ids = sorted(list(current_ids - previous_ids))
    expired_ids = sorted(list(previous_ids - current_ids - cancelled_ids))

    updated = []
    for aid in sorted(list(previous_ids & current_ids)):
        old = previous_alerts[aid]
        new = current_by_id[aid]
        if _fingerprint(old) != _fingerprint(new):
            changes = []
            for field in SEMANTIC_FIELDS:
                if old.get(field) != new.get(field):
                    if field in {"geometry", "geocode", "parameters", "references", "affected_zones"}:
                        changes.append(f"{field} changed")
                    else:
                        changes.append(f"{field}: '{old.get(field, '')}' -> '{new.get(field, '')}'")
            updated.append({"id": aid, "changes": changes, "title": new.get("title", aid)})

    return {
        "new": [current_by_id[aid] for aid in new_ids],
        "updated": updated,
        "expired": [previous_alerts[aid] for aid in expired_ids],
        "cancelled": cancelled,
        "active": current_by_id,
    }
