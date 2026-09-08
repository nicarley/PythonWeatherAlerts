"""Isolated Qt fixtures: no live weather, user settings, audio, or notifications."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest


def configure_gui_app(app):
    """Use predictable native-looking fonts, including with Windows offscreen Qt."""
    import os
    from pathlib import Path
    from PySide6.QtGui import QFont, QFontDatabase

    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf", "seguiemj.ttf"):
        path = fonts / filename
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))


@pytest.fixture(scope="session")
def qapp():
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    widgets = pytest.importorskip("PySide6.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    configure_gui_app(app)
    yield app


@contextmanager
def isolated_gui_window(monkeypatch, tmp_path, app):
    """Create the actual window while containing all external side effects."""
    import PyWeatherAlertGui as gui
    from PySide6.QtCore import QTimer

    monkeypatch.setattr(gui, "QWebEngineView", None)
    monkeypatch.setattr(gui, "ModularNwsApiClient", MagicMock())
    monkeypatch.setattr(gui, "dispatch_notification_channels", MagicMock(return_value={}))
    monkeypatch.setattr(gui.WeatherAlertApp, "_get_user_data_path", lambda self: str(tmp_path))
    monkeypatch.setattr(gui.WeatherAlertApp, "_load_settings", lambda self: None)
    monkeypatch.setattr(gui.WeatherAlertApp, "_save_settings", lambda self: None)
    monkeypatch.setattr(gui.WeatherAlertApp, "_init_system_tray", lambda self: None)
    monkeypatch.setattr(
        gui.WeatherAlertApp, "_initialize_tts_engine", lambda self: self._DummyEngine()
    )
    monkeypatch.setattr(gui.WeatherAlertApp, "_play_alert_sound", MagicMock())
    monkeypatch.setattr(gui.WeatherAlertApp, "_show_desktop_notification", MagicMock())
    # Leave real refresh methods available to state-transition tests after construction.
    with monkeypatch.context() as construction:
        construction.setattr(gui.WeatherAlertApp, "_update_location_data", lambda *args: None)
        window = gui.WeatherAlertApp()
    for timer in window.findChildren(QTimer):
        timer.stop()
    monkeypatch.setattr(window.thread_pool, "start", MagicMock())
    try:
        yield window
    finally:
        for timer in window.findChildren(QTimer):
            timer.stop()
        window.close()
        window.deleteLater()
        app.processEvents()


@pytest.fixture
def gui_window(monkeypatch, tmp_path, qapp):
    with isolated_gui_window(monkeypatch, tmp_path, qapp) as window:
        yield window
