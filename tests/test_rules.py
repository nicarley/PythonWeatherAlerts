from datetime import datetime

import pytest

from weather_alert.rules import evaluate_location_rule, normalize_location_entry, summarize_lifecycle


def test_normalize_location_entry_adds_rules():
    loc = normalize_location_entry({"name": "Home", "id": "62881"})
    assert "rules" in loc
    assert loc["rules"]["min_severity"] == "Minor"


def test_normalize_partial_rules_preserves_nested_defaults_and_user_values():
    original = {
        "name": "Home", "id": "62881",
        "rules": {
            "quiet_hours": {"enabled": True},
            "escalation": {"enabled": False, "radius_miles": 25},
            "audio_profiles": {"night": {"voice_rate": 150}},
        },
    }

    normalized = normalize_location_entry(original)
    rules = normalized["rules"]

    assert rules["quiet_hours"] == {"enabled": True, "start": "22:00", "end": "07:00"}
    assert rules["escalation"]["enabled"] is False
    assert rules["escalation"]["radius_miles"] == 25
    assert rules["escalation"]["min_severity"] == "Severe"
    assert rules["audio_profiles"]["night"]["voice_rate"] == 150
    assert rules["audio_profiles"]["night"]["start"] == "22:00"
    assert rules["audio_profiles"]["day"]["voice_rate"] == 200
    assert original["rules"]["quiet_hours"] == {"enabled": True}

    rules["audio_profiles"]["night"]["voice_rate"] = 180
    assert original["rules"]["audio_profiles"]["night"]["voice_rate"] == 150


@pytest.mark.parametrize("rules", [None, {"quiet_hours": None, "audio_profiles": None}])
def test_normalize_missing_rule_sections_keeps_rules_usable(rules):
    normalized = normalize_location_entry({"id": "62881", "rules": rules})

    allowed, reason = evaluate_location_rule(
        {"title": "Flood Advisory", "severity": "Moderate"},
        normalized["rules"], datetime(2026, 1, 1, 12, 0),
    )

    assert allowed is True
    assert reason == "allowed"
    assert normalized["rules"]["audio_profiles"]["night"]["start"] == "22:00"


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
