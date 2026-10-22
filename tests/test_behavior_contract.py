"""Portable behavior fixtures are an executable desktop contract, not a native pass claim."""

import copy
from datetime import datetime
import json
from pathlib import Path

import pytest

from weather_alert.identity import alert_priority_key, alert_revision, expiry_timestamp
from weather_alert.rules import evaluate_location_rule, normalize_location_entry, summarize_lifecycle


CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "contracts" / "alert-behavior-v1.json").read_text(encoding="utf8")
)


@pytest.mark.parametrize("case", CONTRACT["rules"], ids=lambda case: case["name"])
def test_shared_location_rule_cases(case):
    rules = normalize_location_entry({"rules": case["rules"]})["rules"]
    allowed, reason = evaluate_location_rule(
        case["alert"], rules, datetime.fromisoformat(case["now"]),
        ignore_quiet_hours=case.get("ignore_quiet_hours", False),
    )
    assert allowed is case["allowed"]
    assert case["reason"] in reason


@pytest.mark.parametrize("case", CONTRACT["lifecycle"], ids=lambda case: case["name"])
def test_shared_lifecycle_cases(case):
    previous = {alert["id"]: alert for alert in case["previous"]}
    result = summarize_lifecycle(previous, case["current"])
    for name, ids in case["expected"].items():
        actual = sorted(result[name]) if name == "active" else sorted(alert["id"] for alert in result[name])
        assert actual == sorted(ids)


def test_shared_priority_order_keeps_distant_extreme_above_near_minor():
    actual = sorted(CONTRACT["priority"]["alerts"], key=alert_priority_key)
    assert [alert["id"] for alert in actual] == CONTRACT["priority"]["expected_ids"]


def test_revision_golden_value_and_runtime_metadata_are_stable():
    case = CONTRACT["revision"]
    alert = copy.deepcopy(case["alert"])
    assert alert_revision(alert) == case["expected_sha256"]
    alert.update(case["ignored_patch"])
    assert alert_revision(alert) == case["expected_sha256"]
    assert alert_revision(dict(reversed(list(alert.items())))) == case["expected_sha256"]


@pytest.mark.parametrize("patch", CONTRACT["revision"]["semantic_patches"])
def test_actionable_revision_changes_are_detected_without_upstream_timestamp_change(patch):
    original = copy.deepcopy(CONTRACT["revision"]["alert"])
    changed = {**original, **patch}
    assert alert_revision(changed) != alert_revision(original)
    result = summarize_lifecycle({original["id"]: original}, [changed])
    assert len(result["updated"]) == 1
    assert result["updated"][0]["changes"]


@pytest.mark.parametrize("case", CONTRACT["expiry"])
def test_shared_expiry_utc_contract(case):
    assert expiry_timestamp(case["alert"]) == case["expected"]


def test_group_normalization_preserves_user_group_without_mutating_input():
    original = {"id": "home", "group": "Operations"}
    assert normalize_location_entry(original)["group"] == "Operations"
    assert normalize_location_entry({"id": "home"})["group"] == "Ungrouped"
    assert normalize_location_entry({"id": "home", "group": " "})["group"] == "Ungrouped"
    assert original == {"id": "home", "group": "Operations"}


def test_current_cancel_notice_wins_over_older_active_duplicate():
    active = {"id": "A", "title": "Warning", "severity": "Severe"}
    cancel = {**active, "message_type": "Cancel"}
    result = summarize_lifecycle({"A": active}, [cancel, active])
    assert result["active"] == {}
    assert result["new"] == []
    assert [alert["id"] for alert in result["cancelled"]] == ["A"]


def test_active_unexpired_alerts_removes_exact_boundary_and_cancellation_without_mutation():
    from weather_alert.identity import active_unexpired_alerts

    inputs = [
        {"id": "future", "expires": 101},
        {"id": "boundary", "expires": 100},
        {"id": "unknown-expiry", "expires": "invalid"},
        {"id": "cancelled", "message_type": "Cancel", "expires": 200},
    ]
    result = active_unexpired_alerts(inputs, now=100)
    assert [item["id"] for item in result] == ["future", "unknown-expiry"]
    result[0]["id"] = "changed"
    assert inputs[0]["id"] == "future"
    assert len(inputs) == 4


def test_active_unexpired_alerts_rejects_nonfinite_time():
    from weather_alert.identity import active_unexpired_alerts

    with pytest.raises(ValueError):
        active_unexpired_alerts([], now=float("nan"))
