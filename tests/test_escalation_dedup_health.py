from datetime import datetime

from weather_alert.dedup import AlertDeduplicator
from weather_alert.escalation import evaluate_escalation
from weather_alert.health import DeliveryHealthTracker


def test_escalation_triggers_for_high_severity():
    rules = {"escalation": {"enabled": True, "min_severity": "Severe", "radius_miles": 50}}
    alert = {"title": "Severe Thunderstorm Warning", "event": "Severe Thunderstorm Warning", "severity": "Severe"}
    result = evaluate_escalation(alert, rules, distance_miles=20.0, now=datetime(2026, 1, 1, 12, 0))
    assert result["escalate"] is True
    assert result["override_quiet_hours"] is True


def test_dedup_suppression_blocks_within_cooldown():
    d = AlertDeduplicator(default_cooldown_s=60)
    alert = {"title": "Flood Warning", "event": "Flood Warning", "area_desc": "X"}
    allowed, _ = d.should_send(alert)
    assert allowed is True
    allowed2, reason2 = d.should_send(alert)
    assert allowed2 is False
    assert "cooldown" in reason2


def test_health_tracker_computes_success_rate():
    tracker = DeliveryHealthTracker()
    tracker.record("discord", True, "")
    tracker.record("discord", False, "timeout")
    stats = tracker.stats()
    assert stats["discord"]["attempts"] == 2
    assert stats["discord"]["failures"] == 1
    assert stats["discord"]["success_rate"] == 50.0

