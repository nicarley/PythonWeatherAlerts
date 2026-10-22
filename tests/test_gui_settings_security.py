"""Exercise real settings I/O through isolated windows and an in-memory vault."""
import json
from types import MethodType
from unittest.mock import MagicMock

import PyWeatherAlertGui as gui


# Retain the real methods before the fixture suppresses startup/settings side effects.
LOAD_SETTINGS = gui.WeatherAlertApp._load_settings
SAVE_SETTINGS = gui.WeatherAlertApp._save_settings


def enable_settings_io(window, monkeypatch):
    monkeypatch.setattr(window, "_load_settings", MethodType(LOAD_SETTINGS, window))
    monkeypatch.setattr(window, "_save_settings", MethodType(SAVE_SETTINGS, window))
    monkeypatch.setattr(window, "_update_location_data", MagicMock())
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(gui.QMessageBox, name, MagicMock())


def test_legacy_webhooks_migrate_to_vault_without_remaining_in_settings(gui_window, monkeypatch):
    window = gui_window
    enable_settings_io(window, monkeypatch)
    secrets = {"webhook_url": "https://example.invalid/generic/private-token",
               "discord_webhook_url": "https://example.invalid/discord/private-token",
               "slack_webhook_url": "https://example.invalid/slack/private-token"}
    assert window.settings_manager.save({"locations": [{"id": "62881", "name": "Office"}], **secrets})
    window._load_settings()
    window._save_settings()
    saved = window.settings_manager.load()
    for channel, key in (("generic", "webhook_url"), ("discord", "discord_webhook_url"), ("slack", "slack_webhook_url")):
        assert window.credentials.backend.get_password(window.credentials.service, channel) == secrets[key]
        assert key not in saved
    assert saved["schema_version"] == 2


def test_backup_menu_excludes_even_unmigrated_legacy_credentials(gui_window, monkeypatch, tmp_path):
    window = gui_window
    secret = "https://example.invalid/private-token"
    assert window.settings_manager.save({"locations": [{"id": "62881"}], "webhook_url": secret,
        "discord_webhook_url": secret, "slack_webhook_url": secret})
    destination = tmp_path / "backup.json"
    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    monkeypatch.setattr(gui.QMessageBox, "information", MagicMock())
    window.backup_settings_action.trigger()
    content = destination.read_text(encoding="utf-8")
    assert secret not in content
    assert "webhook_url" not in content
    assert json.loads(content)["locations"][0]["id"] == "62881"
    assert window.settings_manager.load()["webhook_url"] == secret


def test_restore_menu_applies_preferences_and_migrates_legacy_credentials(gui_window, monkeypatch, tmp_path, qapp):
    window = gui_window
    enable_settings_io(window, monkeypatch)
    source = tmp_path / "restore.json"
    secret = "https://example.invalid/restored-secret"
    source.write_text(json.dumps({"schema_version": 2, "locations": [{"id": "KSTL", "name": "Office"}],
        "auto_refresh_content": False, "dark_mode_enabled": True, "webhook_url": secret}), encoding="utf-8")
    monkeypatch.setattr(gui.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    window.restore_settings_action.trigger()
    qapp.processEvents()
    assert window.current_location_id == "KSTL"
    assert window.dark_mode_action.isChecked()
    assert not window.auto_refresh_action.isChecked()
    assert window.credentials.backend.get_password(window.credentials.service, "generic") == secret
    assert "webhook_url" not in window.settings_manager.load()
    gui.QMessageBox.critical.assert_not_called()


def test_partial_vault_failure_does_not_restore_an_older_successful_channel(gui_window, monkeypatch):
    window = gui_window
    enable_settings_io(window, monkeypatch)
    old = "https://example.invalid/old-generic"
    new = "https://example.invalid/new-generic"
    slack = "https://example.invalid/legacy-slack"
    assert window.settings_manager.save({"webhook_url": old, "slack_webhook_url": slack})
    write = window.credentials.backend.set_password

    def fail_slack(service, channel, value):
        if channel == "slack":
            raise RuntimeError("Vault channel unavailable")
        write(service, channel, value)

    monkeypatch.setattr(window.credentials.backend, "set_password", fail_slack)
    window._load_settings()
    window.current_webhook_url = new
    window._save_settings()
    saved = window.settings_manager.load()
    assert saved.get("slack_webhook_url") == slack  # Existing failed migration is recoverable.
    assert "webhook_url" not in saved  # Successfully migrated channel must not resurrect old text.
    window._load_settings()
    assert window.current_webhook_url == new


def test_restore_rejects_invalid_ui_types_before_replacing_saved_settings(gui_window, monkeypatch, tmp_path):
    window = gui_window
    enable_settings_io(window, monkeypatch)
    assert window.settings_manager.save({"locations": [{"id": "62881"}], "dark_mode_enabled": False})
    original = window.settings_manager.load()
    source = tmp_path / "malformed-preferences.json"
    source.write_text(json.dumps({"locations": [{"id": "KSTL"}], "dark_mode_enabled": {"invalid": True}}), encoding="utf-8")
    monkeypatch.setattr(gui.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    window.restore_settings_action.trigger()
    assert window.settings_manager.load() == original
    gui.QMessageBox.critical.assert_called_once()


def test_restore_applies_specialist_visibility_and_workspace_proportions(gui_window, monkeypatch, tmp_path, qapp):
    window = gui_window
    enable_settings_io(window, monkeypatch)
    window.show()
    window.resize(1500, 920)
    qapp.processEvents()
    source = tmp_path / "workspace-preferences.json"
    source.write_text(json.dumps({"locations": [{"id": "62881"}], "show_specialist_tools": True,
        "forecast_view": "daily", "splitter_sizes": {"workbench": [600, 800], "forecast_workspace": [250, 500]}}), encoding="utf-8")
    monkeypatch.setattr(gui.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    window.restore_settings_action.trigger()
    qapp.processEvents()
    assert window.specialist_tools_action.isChecked()
    assert window.web_tabs.isTabVisible(window.web_tabs.indexOf(window.fishing_view))
    assert window.daily_view_button.isChecked()
    assert window.workbench_splitter.sizes()[0] > 500
    assert window.forecast_workspace_splitter.sizes()[0] < 360
