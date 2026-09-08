"""Behavioral checks for the desktop overview and keyboard navigation."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
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


def test_forecast_reflows_and_recovers_space_when_panel_hidden(gui_window, qapp):
    window = gui_window
    window.show()
    window.resize(1280, 800)
    qapp.processEvents()
    assert window.forecast_cards_layout.direction() == QBoxLayout.Direction.TopToBottom
    both_height = window.combined_forecast_widget.maximumHeight()
    window.show_daily_forecast_action.setChecked(False)
    qapp.processEvents()
    assert window.combined_forecast_widget.maximumHeight() < both_height
    window.resize(1800, 1000)
    qapp.processEvents()
    assert window.forecast_cards_layout.direction() == QBoxLayout.Direction.LeftToRight


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
