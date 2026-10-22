"""Behavioral checks for the desktop overview and keyboard navigation."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QBoxLayout, QListWidgetItem


def test_overview_distinguishes_unknown_clear_and_cached(gui_window):
    window = gui_window
    location_id = window.current_location_id
    window.location_runtime_status[location_id] = {"state": "error"}
    window._update_dashboard_summary()
    assert window.hazard_value_label.text() == "Unknown"
    assert window.active_alerts_value_label.text() == "—"
    assert "unavailable" in window.dashboard_subheadline.text()
    assert window.delivery_value_label.text() == "—"

    window.location_runtime_status[location_id] = {"state": "online"}
    window.last_known_data_by_location[location_id] = {"alerts": []}
    window._update_dashboard_summary()
    assert window.active_alerts_value_label.text() == "0"
    assert "No active NWS alerts" in window.dashboard_subheadline.text()

    window.location_runtime_status[location_id] = {"state": "cached"}
    window._update_dashboard_summary()
    assert "last available" in window.dashboard_subheadline.text()
    assert "cached" in window.network_status_indicator.text()


def test_enter_opens_selected_alert_once(gui_window, monkeypatch, qapp):
    import PyWeatherAlertGui as gui

    dialog = MagicMock()
    monkeypatch.setattr(gui, "AlertDetailsDialog", dialog)
    item = QListWidgetItem("Flood Watch")
    item.setData(Qt.ItemDataRole.UserRole + 2, {"title": "Flood Watch"})
    gui_window.alerts_display_area.addItem(item)
    gui_window.alerts_display_area.setCurrentItem(item)
    gui_window.show()
    qapp.processEvents()
    gui_window.alerts_display_area.setFocus()
    QTest.keyClick(gui_window.alerts_display_area, Qt.Key.Key_Return)
    dialog.assert_called_once()
    dialog.return_value.exec.assert_called_once()


def test_forecast_switch_uses_available_workspace(gui_window, qapp):
    window = gui_window
    window.resize(1280, 800)
    window.show()
    qapp.processEvents()
    assert window.hourly_forecast_group.isVisible()
    assert not window.daily_forecast_group.isVisible()
    QTest.mouseClick(window.daily_view_button, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert window.daily_forecast_group.isVisible()
    assert not window.hourly_forecast_group.isVisible()
    assert window.current_forecast_view == "daily"
    assert window.combined_forecast_widget.maximumHeight() > 10000
    assert window.forecast_workspace_splitter.count() == 2
    window.show_daily_forecast_action.trigger()
    qapp.processEvents()
    assert window.hourly_forecast_group.isVisible()
    assert not window.daily_view_button.isEnabled()


def test_theme_switch_refreshes_existing_alert_colors(gui_window):
    window = gui_window
    alert = {"title": "Flood Warning", "severity": "Severe", "_rule_allowed": True}
    window._update_alerts_display_area([alert], window.current_location_id)
    item = window.alerts_display_area.item(0)
    original_color = item.foreground().color()
    original_text = item.text()
    window._on_dark_mode_toggled(True)
    assert item.foreground().color() != original_color
    assert item.text() == original_text


def test_header_monitoring_toggle_does_not_change_speech(gui_window, qapp):
    window = gui_window
    window.show()
    qapp.processEvents()
    original_speech = window.announce_alerts_action.isChecked()
    original_monitoring = window.auto_refresh_action.isChecked()
    QTest.mouseClick(window.monitoring_toggle_button, Qt.MouseButton.LeftButton)
    assert window.auto_refresh_action.isChecked() != original_monitoring
    assert window.announce_alerts_action.isChecked() == original_speech
    assert window.monitoring_toggle_button.isChecked() == window.auto_refresh_action.isChecked()
    assert window.monitoring_state_label.text() == ("Monitoring on" if window.auto_refresh_action.isChecked() else "Monitoring paused")
    QTest.mouseClick(window.monitoring_toggle_button, Qt.MouseButton.LeftButton)
    assert window.auto_refresh_action.isChecked() == original_monitoring


def test_visible_details_button_opens_selected_alert(gui_window, monkeypatch, qapp):
    import PyWeatherAlertGui as gui

    dialog = MagicMock()
    monkeypatch.setattr(gui, "AlertDetailsDialog", dialog)
    item = QListWidgetItem("Severe Thunderstorm Warning")
    item.setData(Qt.ItemDataRole.UserRole + 2, {"title": "Severe Thunderstorm Warning", "instruction": "Go indoors."})
    gui_window.alerts_display_area.addItem(item)
    gui_window.show()
    qapp.processEvents()
    assert not gui_window.alert_details_button.isEnabled()
    QTest.mouseClick(gui_window.alerts_display_area.viewport(), Qt.MouseButton.LeftButton, pos=gui_window.alerts_display_area.visualItemRect(item).center())
    assert gui_window.alert_details_button.isEnabled()
    QTest.mouseClick(gui_window.alert_details_button, Qt.MouseButton.LeftButton)
    dialog.assert_called_once()
    assert dialog.call_args.args[0]["instruction"] == "Go indoors."


def test_setup_collects_location_then_independent_notification_choices(gui_window, qapp):
    from PyWeatherAlertGui import WeatherSetupDialog
    from PySide6.QtWidgets import QDialog

    dialog = WeatherSetupDialog(gui_window)
    dialog.show()
    qapp.processEvents()
    assert not dialog.next_button.isEnabled()
    QTest.keyClicks(dialog.location_name_edit, "Main office")
    QTest.keyClicks(dialog.location_input_edit, "KSTL")
    QTest.keyClicks(dialog.location_group_edit, "Facilities")
    QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert dialog.pages.currentIndex() == 1
    assert dialog.monitoring_check.isChecked()
    assert not dialog.voice_check.isChecked()
    qapp.processEvents()
    QTest.mouseClick(dialog.voice_check, Qt.MouseButton.LeftButton, pos=QPoint(8, dialog.voice_check.height() // 2))
    QTest.mouseClick(dialog.finish_button, Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Accepted
    data = dialog.get_data()
    assert data["location"]["name"] == "Main office"
    assert data["location"]["id"] == "KSTL"
    assert data["auto_refresh_content"] and data["announce_alerts"]
    dialog.deleteLater()


def test_specialist_tools_are_opt_in(gui_window, qapp):
    window = gui_window
    index = window.web_tabs.indexOf(window.fishing_view)
    assert not window.web_tabs.isTabVisible(index)
    window.specialist_tools_action.trigger()
    assert window.web_tabs.isTabVisible(index)
    window.specialist_tools_action.trigger()
    assert not window.web_tabs.isTabVisible(index)


def test_group_filter_changes_watchlist_without_changing_monitoring(gui_window, qapp):
    window = gui_window
    window.locations = [
        {"id": "office", "name": "Office", "group": "Facilities"},
        {"id": "home", "name": "Home", "group": "Family"},
    ]
    window.current_location_id = "office"
    window._update_dashboard_summary()
    window.location_group_filter.setCurrentIndex(window.location_group_filter.findData("Family"))
    assert window.location_overview_list.count() == 1
    assert "Home" in window.location_overview_list.item(0).text()
    assert window.current_location_id == "office"
    assert len(window.locations) == 2
    window.monitoring_coordinator.refresh.assert_not_called()


def test_acknowledgment_records_review_and_keeps_alert_active(gui_window, qapp):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from weather_alert.identity import alert_revision

    window = gui_window
    alert = {"id": "alert-1", "updated": "2026-10-22T12:00:00Z", "title": "Flood Warning", "severity": "Severe", "_rule_allowed": True}
    window._update_alerts_display_area([alert], window.current_location_id)
    window.show()
    qapp.processEvents()
    item = window.alerts_display_area.item(0)
    QTest.mouseClick(window.alerts_display_area.viewport(), Qt.MouseButton.LeftButton, pos=window.alerts_display_area.visualItemRect(item).center())
    assert window.acknowledge_alert_button.isEnabled()

    def review():
        dialog = QApplication.activeModalWidget()
        dialog.operator_edit.setText("Casey")
        dialog.note_edit.setText("Team notified")
        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, review)
    QTest.mouseClick(window.acknowledge_alert_button, Qt.MouseButton.LeftButton)
    acknowledgment = window.operations.acknowledgment(window.current_location_id, "alert-1", alert_revision(alert))
    assert acknowledgment["operator"] == "Casey"
    assert acknowledgment["note"] == "Team notified"
    assert not window.acknowledge_alert_button.isEnabled()
    assert "Flood Warning" in window.alerts_display_area.item(0).text()


def test_operations_only_offers_retry_for_definite_retryable_failure(gui_window, monkeypatch, qapp):
    from types import SimpleNamespace
    from PyWeatherAlertGui import OperationsDialog

    service = MagicMock()
    records = [
        SimpleNamespace(id="uncertain", location_id=gui_window.current_location_id, payload={"title": "Flood Warning"}, alert_id="alert", channel="webhook", state="uncertain", attempts=1, updated_at=1, error="Response lost", retryable=False),
        SimpleNamespace(id="failed", location_id=gui_window.current_location_id, payload={"title": "Flood Warning"}, alert_id="alert", channel="webhook", state="failed", attempts=1, updated_at=1, error="Rate limited", retryable=True),
    ]
    service.records.return_value = records
    monkeypatch.setattr(gui_window, "delivery_service", service)
    dialog = OperationsDialog(gui_window)
    dialog.show()
    qapp.processEvents()
    dialog.delivery_table.selectRow(0)
    assert not dialog.retry_button.isEnabled()
    dialog.delivery_table.selectRow(1)
    assert dialog.retry_button.isEnabled()
    QTest.mouseClick(dialog.retry_button, Qt.MouseButton.LeftButton)
    service.retry_failed.assert_called_once_with("failed")
    dialog.close()


def test_diagnostics_export_is_local_and_excludes_location_identity(gui_window, monkeypatch, tmp_path):
    import json
    import zipfile
    import PyWeatherAlertGui as gui

    destination = tmp_path / "diagnostics.zip"
    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", lambda *args: (str(destination), "ZIP archives (*.zip)"))
    gui_window.operations.record("fetch_duration_ms", "private-location-id", 15)
    gui_window.export_diagnostics_action.trigger()
    with zipfile.ZipFile(destination) as archive:
        text = archive.read("diagnostics.json").decode()
        document = json.loads(text)
    assert "private-location-id" not in text
    assert document["metrics"][0]["kind"] == "fetch_duration_ms"


def test_narrow_window_keeps_optional_status_chips_reachable(gui_window, qapp):
    window = gui_window
    window.show()
    window.resize(1100, 720)
    qapp.processEvents()
    assert window.width() == 1100
    assert window._header_status_wrapped
    assert window.monitoring_toggle_button.geometry().right() <= window.top_status_strip.width()
    window.resize(1500, 920)
    qapp.processEvents()
    assert not window._header_status_wrapped
