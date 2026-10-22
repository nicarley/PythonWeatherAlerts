"""Weather availability and filtering must stay clear during asynchronous refreshes."""

from unittest.mock import MagicMock


def _alert(title="Tornado Warning", alert_id="warning"):
    return {
        "id": alert_id,
        "title": title,
        "severity": "Severe",
        "summary": "Test weather bulletin.",
        "_rule_allowed": True,
        "_notify_allowed": False,
    }


def _cache(window, location_id, alerts=None):
    data = {
        "location_id": location_id,
        "coords": (38.6, -90.2),
        "alerts": alerts or [],
        "current_conditions": {"temperature_f": 72},
        "hourly_forecast": None,
        "daily_forecast": None,
        "fetched_at": 1000,
    }
    window.last_known_data_by_location[location_id] = data
    window.current_alerts_by_location[location_id] = data["alerts"]
    return data


def _list_text(window):
    return "\n".join(
        window.alerts_display_area.item(i).text()
        for i in range(window.alerts_display_area.count())
        if not window.alerts_display_area.item(i).isHidden()
    )


def test_first_refresh_error_does_not_report_all_clear(gui_window):
    from weather_alert.models import COMPONENT_NAMES, ComponentSnapshot, LocationSnapshot

    window = gui_window
    location_id = window.current_location_id
    window.runtime.refresh(location_id)
    generation = window.runtime.generations[location_id]
    window.runtime.on_snapshot(LocationSnapshot(
        location_id=location_id,
        generation=generation,
        started_at=1000,
        finished_at=1001,
        revision=1,
        components={name: ComponentSnapshot(error="NWS timeout", revision=1) for name in COMPONENT_NAMES},
    ))

    assert "status unavailable" in _list_text(window).lower()
    assert "no active alerts" not in window.alerts_meta_label.text().lower()
    assert "unavailable" in window.forecast_board_status_label.text().lower()
    assert "unavailable" in window.map_view.text().lower()


def test_loading_placeholder_is_not_counted_when_filter_changes(gui_window):
    window = gui_window
    window.location_runtime_status[window.current_location_id] = {"state": "loading"}
    window._clear_and_set_loading_states()
    window.all_alerts_button.setChecked(False)
    window.warning_button.setChecked(True)

    window._apply_alert_filters()

    assert window.alerts_display_area.count() == 1
    assert "checking alert status" in window.alerts_meta_label.text().lower()
    assert "of 1 alerts" not in window.alerts_meta_label.text()


def test_same_location_refresh_keeps_known_alerts_and_conditions(gui_window):
    window = gui_window
    location_id = window.current_location_id
    data = _cache(window, location_id, [_alert()])
    window.current_conditions_by_location[location_id] = data["current_conditions"]
    window.location_runtime_status[location_id] = {"state": "online"}
    window._update_alerts_display_area(data["alerts"], location_id)
    original_item = window.alerts_display_area.item(0)

    window._update_location_data(location_id)

    assert window.alerts_display_area.item(0) is original_item
    assert "Tornado Warning" in _list_text(window)
    assert window.current_conditions_by_location[location_id] == data["current_conditions"]
    assert "refreshing" in window.alerts_meta_label.text().lower()
    window.monitoring_coordinator.refresh.assert_called_once()
    assert window.runtime.generations[location_id] == 1
    assert location_id in window.runtime.active


def test_location_switch_starts_independent_generation_and_clears_previous_location(gui_window):
    window = gui_window
    first_id = window.current_location_id
    first_data = _cache(window, first_id, [_alert()])
    window.location_runtime_status[first_id] = {"state": "online"}
    window._update_alerts_display_area(first_data["alerts"], first_id)
    window.current_coords = first_data["coords"]
    window.locations = [*window.locations, {"name": "Second station", "id": "second"}]
    window.location_combo.blockSignals(True)
    window.location_combo.addItem("Second station", "second")
    second_index = window.location_combo.findData("second")
    window.location_combo.blockSignals(False)
    window._update_location_data(first_id)

    window.location_combo.setCurrentIndex(second_index)

    assert window._pending_location_id is None
    assert window.runtime.active == {first_id, "second"}
    assert window.runtime.generations == {first_id: 1, "second": 2}
    assert window.current_coords is None
    assert "Tornado Warning" not in _list_text(window)
    assert "Second station" in window.alerts_meta_label.text()
    assert "Second station" in window.map_view.text()
    assert window.location_runtime_status["second"]["state"] == "loading"
    assert window.monitoring_coordinator.refresh.call_count == 2


def test_switch_uses_selected_locations_cached_alerts(gui_window):
    window = gui_window
    first_id = window.current_location_id
    _cache(window, first_id, [_alert()])
    second_alert = _alert("Flood Watch", "second-watch")
    _cache(window, "second", [second_alert])
    window._displayed_location_id = first_id
    window.locations = [*window.locations, {"name": "Second station", "id": "second"}]
    window.current_location_id = "second"

    window._update_location_data("second")

    assert "Flood Watch" in _list_text(window)
    assert "Tornado Warning" not in _list_text(window)
    assert window._displayed_location_id == "second"
    assert "refreshing" in window.forecast_board_status_label.text().lower()


def test_specific_filter_excludes_generic_alert_and_explains_empty_result(gui_window):
    window = gui_window
    window.location_runtime_status[window.current_location_id] = {"state": "online"}
    window._update_alerts_display_area(
        [_alert("Special Weather Statement", "statement")], window.current_location_id
    )
    window.all_alerts_button.setChecked(False)
    window.warning_button.setChecked(True)

    window._apply_alert_filters()
    window._apply_alert_filters()

    assert "Special Weather Statement" not in _list_text(window)
    assert "No alerts match these filters" in _list_text(window)
    assert "showing 0 of 1 alerts" in window.alerts_meta_label.text()
    assert window.alerts_display_area.count() == 2

    window.all_alerts_button.setChecked(True)
    window._apply_alert_filters()

    assert "Special Weather Statement" in _list_text(window)
    assert "No alerts match" not in _list_text(window)
    assert window.alerts_display_area.count() == 1


def test_successful_empty_check_remains_distinct_from_unavailable(gui_window):
    window = gui_window
    window.location_runtime_status[window.current_location_id] = {"state": "online"}

    window._update_alerts_display_area([], window.current_location_id)

    assert "No active alerts in the last successful check" in _list_text(window)
    assert "unavailable" not in window.alerts_meta_label.text().lower()
