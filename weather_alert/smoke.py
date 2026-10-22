"""Offline packaging smoke test using disposable data and inert external adapters."""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


def run_smoke(gui):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent
    app = gui.QApplication.instance() or gui.QApplication([])
    app.setStyle("Fusion")
    # A local base is configurable in restricted runners; no existing app data is read.
    base = os.environ.get("PYWEATHER_SMOKE_TMP")
    with tempfile.TemporaryDirectory(prefix="pyweather-smoke-", dir=base) as directory:
        from contextlib import ExitStack
        from weather_alert import runtime
        with ExitStack() as stack:
            for target, name, value in (
                (gui, "QWebEngineView", None),
                (gui, "ModularNwsApiClient", MagicMock()),
                (gui, "CredentialStore", MagicMock()),
                (runtime, "SpeechQueue", MagicMock()),
                (runtime, "MonitoringCoordinator", MagicMock()),
                (runtime.DeliveryService, "start", lambda self: None),
                (gui.WeatherAlertApp, "_get_user_data_path", lambda self: directory),
                (gui.WeatherAlertApp, "_load_settings", lambda self: None),
                (gui.WeatherAlertApp, "_save_settings", lambda self: None),
                (gui.WeatherAlertApp, "_init_system_tray", lambda self: None),
                (gui.WeatherAlertApp, "_update_location_data", lambda *args: None),
            ):
                stack.enter_context(patch.object(target, name, value))
            window = gui.WeatherAlertApp()
            window.show()
            for width, height in ((1280, 800), (1500, 920)):
                window.resize(width, height)
                app.processEvents()
                if window.centralWidget().width() <= 0:
                    raise RuntimeError("Window did not render")
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
    print("PyWeatherAlert offline smoke test passed")
    return 0
