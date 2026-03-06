from datetime import datetime

from weather_alert.rules import evaluate_location_rule, normalize_location_entry, summarize_lifecycle


def test_normalize_location_entry_adds_rules():
    loc = normalize_location_entry({"name": "Home", "id": "62881"})
    assert "rules" in loc
    assert loc["rules"]["min_severity"] == "Minor"


def test_evaluate_rule_blocks_below_min_severity():
    rules = {
        "min_severity": "Severe",
        "types": ["warning", "watch", "advisory"],
        "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00"},
    }
    allowed, reason = evaluate_location_rule({"title": "Flood Advisory", "severity": "Moderate"}, rules, datetime(2026, 1, 1, 12, 0))
    assert allowed is False
    assert "below min severity" in reason


def test_summarize_lifecycle_identifies_new_updated_and_expired():
    previous = {
        "A": {"id": "A", "title": "Alert A", "updated": "1", "severity": "Minor", "summary": "old"},
        "B": {"id": "B", "title": "Alert B", "updated": "1", "severity": "Moderate", "summary": "same"},
    }
    current = [
        {"id": "B", "title": "Alert B", "updated": "2", "severity": "Severe", "summary": "same"},
        {"id": "C", "title": "Alert C", "updated": "1", "severity": "Minor", "summary": "new"},
    ]
    result = summarize_lifecycle(previous, current)
    assert len(result["new"]) == 1
    assert result["new"][0]["id"] == "C"
    assert len(result["updated"]) == 1
    assert result["updated"][0]["id"] == "B"
    assert len(result["expired"]) == 1
    assert result["expired"][0]["id"] == "A"
