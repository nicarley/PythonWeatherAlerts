"""Integration of source updates and recovery, with all external effects stubbed."""
import time
from dataclasses import replace
from unittest.mock import MagicMock

from weather_alert.models import COMPONENT_NAMES, ComponentSnapshot, LocationSnapshot


def alert(alert_id="warning", instruction="Take shelter now"):
    return {"id": alert_id, "title": "Tornado Warning", "event": "Tornado Warning",
            "severity": "Extreme", "urgency": "Immediate", "certainty": "Observed",
            "summary": "Simulated warning", "instruction": instruction}


def snapshot(window, alerts, *, generation=1, revision=1, complete=False, error=None):
    components = {name: ComponentSnapshot(loading=not complete) for name in COMPONENT_NAMES}
    components["alerts"] = ComponentSnapshot(data=alerts, fetched_at=time.time() if alerts is not None else None,
                                              error=error, revision=revision)
    if complete:
        components["hourly_forecast"] = ComponentSnapshot(error="Forecast unavailable")
    return LocationSnapshot(window.current_location_id, generation, time.time(), coords=(38.6, -90.2),
                            components=components, revision=revision, finished_at=time.time() if complete else None)


def begin(window, generation=1):
    runtime = window.runtime
    runtime.generations[window.current_location_id] = generation
    runtime.active.add(window.current_location_id)
    window._check_in_progress = True
    return runtime


def test_alerts_are_processed_before_forecast_and_optional_sources_finish(gui_window):
    window = gui_window
    runtime = begin(window)
    runtime.on_snapshot(snapshot(window, [alert()]))
    assert window.current_alerts_by_location[window.current_location_id][0]["id"] == "warning"
    assert window._show_desktop_notification.call_count == 1
    assert window._check_in_progress
    assert window.primary_hazard_title_label.text() == "Tornado Warning"
    assert window.hazard_instruction_label.text() == "Take shelter now"
    partial = snapshot(window, [alert()], revision=2, complete=True)
    runtime.on_snapshot(partial)
    assert not window._check_in_progress
    assert window._show_desktop_notification.call_count == 1
    assert window.location_runtime_status[window.current_location_id]["state"] == "online"
    assert "partly unavailable" in window.forecast_board_status_label.text()


def test_stale_generation_cannot_overwrite_current_alerts(gui_window):
    runtime = begin(gui_window, generation=2)
    runtime.on_snapshot(snapshot(gui_window, [alert()], generation=2))
    runtime.on_snapshot(snapshot(gui_window, [], generation=1, complete=True, revision=9))
    assert gui_window.current_alerts_by_location[gui_window.current_location_id][0]["id"] == "warning"
    assert gui_window.current_location_id in runtime.active


def test_missing_alert_source_never_reports_all_clear_when_forecast_finishes(gui_window):
    runtime = begin(gui_window)
    runtime.on_snapshot(snapshot(gui_window, None, complete=True, error="Alert endpoint unavailable"))
    assert gui_window.location_runtime_status[gui_window.current_location_id]["alerts_available"] is False
    assert gui_window.hazard_value_label.text() == "Unknown"
    assert "unavailable" in gui_window.alerts_display_area.item(0).text().lower()
    assert not gui_window._check_in_progress


def test_ui_exception_still_releases_refresh_scheduler(gui_window, monkeypatch):
    runtime = begin(gui_window)
    monkeypatch.setattr(gui_window, "_render_cached_location_data", MagicMock(side_effect=RuntimeError("render")))
    runtime.on_snapshot(snapshot(gui_window, [alert()], complete=True))
    assert not gui_window._check_in_progress
    assert gui_window.current_location_id not in runtime.active
    assert any(metric["kind"] == "processing_failure" for metric in runtime.operations.metrics())


def test_revisions_notify_once_per_location_even_when_seen_history_exists(gui_window):
    window = gui_window
    a = alert()
    window.alert_history_manager.seen_alerts.add(a["id"])
    window.runtime.process_alerts([dict(a)], window.current_location_id)
    window.runtime.process_alerts([dict(a)], window.current_location_id)
    window.runtime.process_alerts([alert(instruction="Move to a basement")], window.current_location_id)
    window.locations.append({"id": "second", "name": "Second"})
    window.runtime.process_alerts([dict(a)], "second")
    assert window._show_desktop_notification.call_count == 3


def test_channels_are_independent_and_seen_history_does_not_block_outbox(gui_window):
    window = gui_window
    window.locations[0]["rules"]["webhook_enabled"] = True
    window.current_enable_webhook_notifications = True
    window.current_enable_discord_notifications = True
    a = alert()
    window.runtime.process_alerts([a], window.current_location_id)
    window.runtime.enqueue_alerts(window.current_location_id, [a])
    window.runtime.enqueue_alerts(window.current_location_id, [a])
    records = window.delivery_service.records()
    assert len(records) == 2
    assert {record.channel for record in records} == {"generic", "discord"}
    assert all(record.destination.startswith("credential:") for record in records)
    assert all(record.state == "queued" for record in records)


def test_speech_setting_does_not_resume_weather_monitoring(gui_window):
    window = gui_window
    window.auto_refresh_action.setChecked(False)
    window.announce_alerts_action.setChecked(True)
    window._update_main_timer_state()
    assert not window.main_check_timer.isActive()
    assert "paused" in window.top_countdown_label.text().lower()


def test_mute_clears_pending_speech_without_talking_to_engine(gui_window):
    gui_window._on_mute_toggled(True)
    gui_window.speech_queue.clear.assert_called_once()


def test_expired_cached_warning_becomes_unknown_until_fresh_check(gui_window):
    window = gui_window
    runtime = begin(window)
    now = time.time()
    warning = dict(alert(), expires=now + 10)
    first = snapshot(window, [warning])
    runtime.on_snapshot(first)
    assert window.primary_hazard_title_label.text() == "Tornado Warning"

    assert runtime.expire_cached_alerts(now=now + 11) == 1

    location_id = window.current_location_id
    assert window.current_alerts_by_location[location_id] == []
    assert window.location_runtime_status[location_id]["alerts_available"] is False
    assert window.hazard_value_label.text() == "Unknown"
    assert "no active alerts" not in window.primary_hazard_title_label.text().lower()
    assert "no active alerts" not in window.alerts_meta_label.text().lower()
    assert location_id not in runtime.verified_locations
    assert not window.escalation_repeat_state
    assert runtime.operations.load_snapshots()[location_id]["alerts_expired_since_check"] is True

    # A late forecast completion carrying the original alert component must not
    # manufacture another alert check or resurrect the expired hazard.
    late = replace(first, revision=first.revision + 1, finished_at=now + 12)
    runtime.on_snapshot(late)
    assert window.location_runtime_status[location_id]["alerts_available"] is False
    assert window.current_alerts_by_location[location_id] == []
    assert window.hazard_value_label.text() == "Unknown"

    runtime.generations[location_id] = 2
    fresh = snapshot(window, [], generation=2, revision=1, complete=True)
    runtime.on_snapshot(fresh)
    assert window.location_runtime_status[location_id]["alerts_available"] is True
    assert window.current_alerts_by_location[location_id] == []
    assert "no active alerts" in window.primary_hazard_title_label.text().lower()
    assert location_id in runtime.verified_locations


def test_expiry_pruning_keeps_other_unexpired_hazards(gui_window):
    window = gui_window
    runtime = begin(window)
    now = time.time()
    runtime.on_snapshot(snapshot(window, [
        dict(alert("ends-first"), expires=now + 1),
        dict(alert("still-valid"), title="Flood Warning", expires=now + 100),
    ]))

    runtime.expire_cached_alerts(now=now + 2)

    assert [item["id"] for item in window.current_alerts_by_location[window.current_location_id]] == ["still-valid"]
    assert window.location_runtime_status[window.current_location_id]["alerts_available"] is True
    assert window.primary_hazard_title_label.text() == "Flood Warning"
    assert window.location_runtime_status[window.current_location_id]["state"] == "cached"


def test_fresh_response_with_only_already_expired_records_confirms_no_valid_active_alerts(gui_window):
    window = gui_window
    runtime = begin(window)
    runtime.on_snapshot(snapshot(window, [dict(alert(), expires=time.time() - 60)], complete=True))

    assert window.current_alerts_by_location[window.current_location_id] == []
    assert window.location_runtime_status[window.current_location_id]["alerts_available"] is True
    assert "no active alerts" in window.primary_hazard_title_label.text().lower()
    window._show_desktop_notification.assert_not_called()
    assert not window.escalation_repeat_state


def test_restore_prunes_expired_cache_and_preserves_unknown_marker_across_restart(gui_window):
    window = gui_window
    runtime = window.runtime
    location_id = window.current_location_id
    now = time.time()
    runtime.operations.save_snapshot(location_id, {
        "location_id": location_id,
        "alerts": [dict(alert(), expires=now - 10, _rule_allowed=True)],
        "fetched_at": now - 100,
        "coords": [38.6, -90.2],
        "component_status": {"alerts": {"fetched_at": now - 100}},
    })

    runtime.restore()
    window._render_cached_location_data(location_id)
    window._update_dashboard_summary()

    assert window.current_alerts_by_location[location_id] == []
    assert window.location_runtime_status[location_id]["alerts_available"] is False
    assert window.hazard_value_label.text() == "Unknown"
    saved = runtime.operations.load_snapshots()[location_id]
    assert saved["alerts"] == []
    assert saved["alerts_expired_since_check"] is True

    runtime._expired_cache_locations.clear()
    runtime.restore()
    assert window.location_runtime_status[location_id]["alerts_available"] is False
    assert location_id in runtime._expired_cache_locations


def test_audit_write_failures_do_not_prevent_warning_display_or_independent_effects(gui_window, monkeypatch):
    window = gui_window
    runtime = begin(window)
    monkeypatch.setattr(window, "_record_lifecycle_events", MagicMock(side_effect=OSError("disk full")))
    monkeypatch.setattr(window.alert_history_manager, "add_alert", MagicMock(side_effect=OSError("disk full")))
    monkeypatch.setattr(runtime.operations, "record", MagicMock(side_effect=OSError("disk full")))

    runtime.on_snapshot(snapshot(window, [alert()], complete=True))

    assert window.primary_hazard_title_label.text() == "Tornado Warning"
    assert window._show_desktop_notification.call_count == 1
    assert window.location_runtime_status[window.current_location_id]["alerts_available"] is True
    assert not window._check_in_progress


def test_rule_suppression_cancels_pending_recovery_before_location_is_reenabled(gui_window):
    from weather_alert.identity import alert_revision

    window = gui_window
    runtime = begin(window)
    location_id = window.current_location_id
    warning = alert()
    window.locations[0]["rules"]["webhook_enabled"] = True
    window.locations[0]["rules"]["types"] = ["advisory"]
    window.current_enable_webhook_notifications = True
    pending = runtime.delivery.enqueue(
        alert_id=warning["id"], revision=alert_revision(warning), location_id=location_id,
        channel="generic", destination="credential:generic", payload={"title": "Warning"},
    )

    runtime.on_snapshot(snapshot(window, [warning], complete=True))

    assert runtime.delivery.get(pending.id).state == "cancelled"
    assert window.current_alerts_by_location[location_id][0]["_notify_allowed"] is False
    assert window.primary_hazard_title_label.text() == "Tornado Warning"


def test_intentional_speech_clear_is_not_reported_as_failure(gui_window, monkeypatch):
    from weather_alert.speech import SpeechResult

    runtime = gui_window.runtime
    monkeypatch.setattr(runtime, "record", MagicMock())
    runtime.on_speech(SpeechResult("Pending utterance", "pending", False, "Queued speech cleared.", cancelled=True))
    runtime.record.assert_not_called()


def test_alert_expiring_between_fetch_and_queued_callback_does_not_establish_all_clear(gui_window):
    window = gui_window
    runtime = begin(window)
    now = time.time()
    response = snapshot(window, [dict(alert(), expires=now - 5)], complete=True)
    components = dict(response.components)
    components["alerts"] = replace(components["alerts"], fetched_at=now - 10)
    runtime.on_snapshot(replace(response, components=components))

    assert window.current_alerts_by_location[window.current_location_id] == []
    assert window.location_runtime_status[window.current_location_id]["alerts_available"] is False
    assert window.hazard_value_label.text() == "Unknown"
    assert window.current_location_id not in runtime.verified_locations
    window._show_desktop_notification.assert_not_called()


def test_fresh_alert_rearms_repeat_after_restart_without_replaying_first_notification(gui_window):
    window = gui_window
    warning = alert()
    runtime = window.runtime
    runtime.process_alerts([dict(warning)], window.current_location_id)
    assert window._show_desktop_notification.call_count == 1
    window.escalation_repeat_state.clear()
    runtime.process_alerts([dict(warning)], window.current_location_id)
    assert window._show_desktop_notification.call_count == 1
    assert f"{window.current_location_id}:warning" in window.escalation_repeat_state
    quiet = dict(warning, severity="Minor", event="Wind Advisory", title="Wind Advisory")
    runtime.process_alerts([quiet], window.current_location_id)
    assert f"{window.current_location_id}:warning" not in window.escalation_repeat_state
