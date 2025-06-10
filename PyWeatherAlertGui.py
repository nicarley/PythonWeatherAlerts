import sys
import requests
import feedparser
import pyttsx3
import time
import logging
import os
import json  # For saving/loading settings
import pgeocode  # For zip code to lat/lon conversion
# import xml.etree.ElementTree as ET  # No longer needed for DWML
versionnumber = "2025.06.09"

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QMessageBox,
    QStatusBar, QCheckBox, QSplitter
)
from PySide6.QtCore import Qt, QTimer, Slot, QUrl
from PySide6.QtGui import QTextCursor, QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView

# Note: If PySide6.QtWebEngineWidgets is not found, you might need to install it:
# pip install PySide6-WebEngine

# --- Configuration ---
# These will be the ultimate fallbacks if settings.txt is missing or corrupt
FALLBACK_INITIAL_CHECK_INTERVAL_MS = 900 * 1000  # Default: 15 minutes
FALLBACK_DEFAULT_INTERVAL_KEY = "15 Minutes"
FALLBACK_DEFAULT_STATION_ID = "KSLO"
FALLBACK_INITIAL_REPEATER_INFO = ""
# FALLBACK_DEFAULT_ZIP_CODE = "90210" # No longer needed
FALLBACK_ANNOUNCE_ALERTS_CHECKED = False
FALLBACK_SHOW_LOG_CHECKED = False

CHECK_INTERVAL_OPTIONS = {
    "1 Minute": 1 * 60 * 1000,
    "5 Minutes": 5 * 60 * 1000,
    "10 Minutes": 10 * 60 * 1000,
    "15 Minutes": 15 * 60 * 1000,
    "30 Minutes": 30 * 60 * 1000,
    "1 Hour": 60 * 60 * 1000,
}

NWS_STATION_API_URL_TEMPLATE = "https://api.weather.gov/stations/{station_id}"
# DWML_FORECAST_URL_TEMPLATE = "https://forecast.weather.gov/MapClick.php?lat={latitude}&lon={longitude}&unit=0&lg=english&FcstType=dwml" # No longer needed

WEATHER_URL_PREFIX = "https://api.weather.gov/alerts/active.atom?point="
WEATHER_URL_SUFFIX = "&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Future%2CExpected"

# URL for the embedded radar
RADAR_URL = "https://radar.weather.gov/?settings=v1_eyJhZ2VuZGEiOnsiaWQiOm51bGwsImNlbnRlciI6Wy04OS41MTcsMzguMTA0XSwibG9jYXRpb24iOm51bGwsInpvb20iOjguMDI4MDQ0MTQyMjY0NzY4fSwiYW5pbWF0aW5nIjp0cnVlLCJiYXNlIjoic3RhbmRhcmQiLCJhcnRjYyI6ZmFsc2UsImNvdW50eSI6ZmFsc2UsImN3YSI6ZmFsc2UsInJmYyI6ZmFsc2UsInN0YXRlIjpmYWxzZSwibWVudSI6dHJ1ZSwic2hvcnRGdXNlZE9ubHkiOmZhbHNlLCJvcGFjaXR5Ijp7ImFsZXJ0cyI6MC44LCJsb2NhbCI6MC42LCJsb2NhbFN0YXRpb25zIjowLjgsIm5hdGlvbmFsIjowLjZ9fQ%3D%3D"

SETTINGS_FILE_NAME = "settings.txt"
RESOURCES_FOLDER_NAME = "resources"

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class WeatherAlertApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Weather Alert Monitor Version {versionnumber}")
        self.setGeometry(100, 100, 800, 800)  # Adjusted size back

        # Initialize default values (will be overridden by _load_settings if successful)
        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.current_station_id = FALLBACK_DEFAULT_STATION_ID
        self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
        # self.current_zip_code = FALLBACK_DEFAULT_ZIP_CODE # No longer needed
        self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
        self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED

        self._load_settings()  # Load settings before UI initialization

        # --- Set the Window Icon ---
        self._set_window_icon()

        self.seen_alert_ids = set()
        self.tts_engine = self._initialize_tts_engine()
        self.is_tts_dummy = isinstance(self.tts_engine, self._DummyEngine)

        self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
            self.current_interval_key,
            FALLBACK_INITIAL_CHECK_INTERVAL_MS
        )

        self.main_check_timer = QTimer(self)
        self.main_check_timer.timeout.connect(self.perform_check_cycle)

        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_countdown_display)
        self.remaining_time_seconds = 0

        # self.geo_locator = pgeocode.Nominatim('us')  # No longer needed for forecast

        self._init_ui()  # Creates UI elements using current_... values

        # Initially hide the log area if that's the default
        self.log_area.setVisible(self.current_show_log_checked)
        self.show_log_checkbox.setChecked(self.current_show_log_checked)  # Sync checkbox
        self.announce_alerts_checkbox.setChecked(self.current_announce_alerts_checked)  # Sync checkbox

        if self.is_tts_dummy:
            self.log_to_gui(
                "TTS engine failed to initialize. Using fallback (logging to console/GUI instead of speaking).",
                level="ERROR")
        else:
            self.log_to_gui("TTS engine initialized successfully.", level="INFO")

        self.log_to_gui(
            f"Monitoring weather alerts for station: {self.station_id_entry.text()}",
            level="INFO")
        # self.log_to_gui(f"Forecast will be attempted for ZIP: {self.zip_code_entry.text()}", level="INFO") # No longer needed

        if self.announce_alerts_checkbox.isChecked():
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(1000, self.perform_check_cycle)  # Start first check
        else:
            self.log_to_gui("Alert announcements disabled. Check the box to start.", level="INFO")
            self.countdown_label.setText("Next check in: --:-- (Paused)")

    def _set_window_icon(self):
        base_path = os.path.dirname(os.path.abspath(__file__))
        icon_path_png = os.path.join(base_path, RESOURCES_FOLDER_NAME, "icon.png")
        icon_path_ico = os.path.join(base_path, RESOURCES_FOLDER_NAME, "icon.ico")
        app_icon = QIcon()
        if os.path.exists(icon_path_png):
            app_icon.addFile(icon_path_png)
        elif os.path.exists(icon_path_ico):
            app_icon.addFile(icon_path_ico)
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
            logging.info("Application icon loaded successfully.")
        else:
            logging.warning(
                f"Could not load application icon from '{RESOURCES_FOLDER_NAME}/icon.png' or '{RESOURCES_FOLDER_NAME}/icon.ico'.")

    def _get_resources_path(self):
        """Gets the absolute path to the resources directory, creating it if necessary."""
        base_path = os.path.dirname(os.path.abspath(__file__))
        resources_path = os.path.join(base_path, RESOURCES_FOLDER_NAME)
        if not os.path.exists(resources_path):
            try:
                os.makedirs(resources_path)
                logging.info(f"Created resources directory: {resources_path}")
            except OSError as e:
                logging.error(f"Could not create resources directory {resources_path}: {e}")
                return None
        return resources_path

    def _load_settings(self):
        resources_path = self._get_resources_path()
        if not resources_path:
            logging.error("Cannot load settings, resources path issue.")
            return

        settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        try:
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
                    self.current_repeater_info = settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO)
                    self.current_station_id = settings.get("station_id", FALLBACK_DEFAULT_STATION_ID)
                    self.current_interval_key = settings.get("check_interval_key", FALLBACK_DEFAULT_INTERVAL_KEY)
                    # self.current_zip_code = settings.get("zip_code", FALLBACK_DEFAULT_ZIP_CODE) # No longer needed
                    self.current_announce_alerts_checked = settings.get("announce_alerts",
                                                                        FALLBACK_ANNOUNCE_ALERTS_CHECKED)
                    self.current_show_log_checked = settings.get("show_log", FALLBACK_SHOW_LOG_CHECKED)
                    logging.info(f"Settings loaded from {settings_file}")
            else:
                logging.info(f"Settings file not found at {settings_file}. Using fallback defaults.")
        except (json.JSONDecodeError, IOError, KeyError) as e:
            logging.error(f"Error loading settings from {settings_file}: {e}. Using fallback defaults.")
            self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
            self.current_station_id = FALLBACK_DEFAULT_STATION_ID
            self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
            # self.current_zip_code = FALLBACK_DEFAULT_ZIP_CODE # No longer needed
            self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
            self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED

    @Slot()
    def _save_settings(self):
        resources_path = self._get_resources_path()
        if not resources_path:
            self.log_to_gui("Cannot save settings, resources path issue.", level="ERROR")
            QMessageBox.critical(self, "Error", "Could not access resources directory to save settings.")
            return

        settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        settings = {
            "repeater_info": self.repeater_entry.text(),
            "station_id": self.station_id_entry.text(),
            "check_interval_key": self.interval_combobox.currentText(),
            # "zip_code": self.zip_code_entry.text(), # No longer needed
            "announce_alerts": self.announce_alerts_checkbox.isChecked(),
            "show_log": self.show_log_checkbox.isChecked()
        }
        try:
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            self.log_to_gui(f"Settings saved to {settings_file}", level="INFO")
            self.update_status(f"Defaults saved to {settings_file}")
            QMessageBox.information(self, "Settings Saved", f"Defaults saved successfully to {settings_file}")
        except (IOError, OSError) as e:
            self.log_to_gui(f"Error saving settings to {settings_file}: {e}", level="ERROR")
            QMessageBox.critical(self, "Error", f"Could not save settings: {e}")

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Configuration Frame ---
        config_group = QWidget()
        config_layout = QGridLayout(config_group)
        config_layout.addWidget(QLabel("Repeater Info:"), 0, 0, Qt.AlignmentFlag.AlignLeft)
        self.repeater_entry = QLineEdit(self.current_repeater_info)
        config_layout.addWidget(self.repeater_entry, 0, 1, 1, 3) # Span across remaining columns

        config_layout.addWidget(QLabel("NWS Station ID (for Alerts):"), 1, 0, Qt.AlignmentFlag.AlignLeft)
        self.station_id_entry = QLineEdit(self.current_station_id)
        self.station_id_entry.setFixedWidth(150)
        config_layout.addWidget(self.station_id_entry, 1, 1, Qt.AlignmentFlag.AlignLeft)
        # Removed Zip Code for Forecast
        config_layout.setColumnStretch(2, 1) # Adjust column stretch as needed
        config_layout.setColumnStretch(3, 1) # Adjust column stretch as needed


        main_layout.addWidget(config_group)

        # --- Controls Frame ---
        controls_group = QWidget()
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        self.speak_reset_button = QPushButton("Speak Repeater Info & Reset Timer")
        self.speak_reset_button.clicked.connect(self._on_speak_and_reset_button_press)
        controls_layout.addWidget(self.speak_reset_button)

        self.announce_alerts_checkbox = QCheckBox("Announce Alerts")
        self.announce_alerts_checkbox.stateChanged.connect(self._on_announce_alerts_toggled)
        controls_layout.addWidget(self.announce_alerts_checkbox)

        self.show_log_checkbox = QCheckBox("Show Log")
        self.show_log_checkbox.stateChanged.connect(self._on_show_log_toggled)
        controls_layout.addWidget(self.show_log_checkbox)

        self.save_defaults_button = QPushButton("Save Current as Defaults")
        self.save_defaults_button.clicked.connect(self._save_settings)
        controls_layout.addWidget(self.save_defaults_button)

        controls_layout.addWidget(QLabel("Check Interval:"))
        self.interval_combobox = QComboBox()
        self.interval_combobox.addItems(CHECK_INTERVAL_OPTIONS.keys())
        self.interval_combobox.setCurrentText(self.current_interval_key)
        self.interval_combobox.currentTextChanged.connect(self._on_interval_selected)
        controls_layout.addWidget(self.interval_combobox)

        controls_layout.addStretch(1)
        self.countdown_label = QLabel("Next check in: --:--")
        font = self.countdown_label.font()
        font.setPointSize(10)
        self.countdown_label.setFont(font)
        controls_layout.addWidget(self.countdown_label)
        main_layout.addWidget(controls_group)

        # --- Removed Forecast Display Area ---

        # --- Splitter for Web View and Log Area ---
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.web_view = QWebEngineView()
        self.web_view.setUrl(QUrl(RADAR_URL))
        self.splitter.addWidget(self.web_view)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.splitter.addWidget(self.log_area)
        main_layout.addWidget(self.splitter, 1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.update_status("Application started. Configure and check 'Announce Alerts' to begin.")

    def _initialize_tts_engine(self):
        """Initializes and returns the TTS engine. Returns a dummy if fails."""
        try:
            engine = pyttsx3.init()
            if engine is None:
                raise RuntimeError("pyttsx3.init() returned None")
            logging.info("TTS engine initialized successfully by app.")
            return engine
        except Exception as e:
            logging.error(f"App: Failed to initialize TTS engine: {e}. Text-to-speech will use a fallback.")
            return self._DummyEngine()

    class _DummyEngine:
        """Fallback TTS engine that logs instead of speaking."""
        def say(self, text, name=None): logging.info(f"TTS (Fallback): {text}")
        def runAndWait(self): pass
        def stop(self): pass
        def isBusy(self): return False
        def getProperty(self, name): return None
        def setProperty(self, name, value): pass

    def log_to_gui(self, message, level="INFO"):
        """Appends a message to the GUI log area (newest at the top) and console log."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}"
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.log_area.setTextCursor(cursor)
        self.log_area.insertPlainText(formatted_message + "\n")
        if level == "ERROR": logging.error(message)
        elif level == "WARNING": logging.warning(message)
        elif level == "DEBUG": logging.debug(message)
        else: logging.info(message)

    def update_status(self, message):
        self.status_bar.showMessage(message)

    def _format_time(self, total_seconds):
        """Formats total seconds into MM:SS or HH:MM:SS string."""
        if total_seconds < 0: total_seconds = 0
        minutes, seconds = divmod(int(total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @Slot()
    def _update_countdown_display(self):
        """Updates the countdown label every second."""
        if self.remaining_time_seconds > 0:
            self.remaining_time_seconds -= 1
        if not self.announce_alerts_checkbox.isChecked() and self.remaining_time_seconds <= 0 :
             self.countdown_label.setText("Next check in: --:-- (Paused)")
        else:
            self.countdown_label.setText(f"Next check in: {self._format_time(self.remaining_time_seconds)}")

    def _reset_and_start_countdown(self, total_seconds_for_interval):
        """Resets the countdown timer to the new interval and starts updating the display."""
        self.countdown_timer.stop()
        self.remaining_time_seconds = total_seconds_for_interval
        self.countdown_label.setText(f"Next check in: {self._format_time(self.remaining_time_seconds)}")
        if total_seconds_for_interval > 0 and self.announce_alerts_checkbox.isChecked():
            self.countdown_timer.start(1000)
        elif not self.announce_alerts_checkbox.isChecked():
            self.countdown_label.setText("Next check in: --:-- (Paused)")

    @Slot(int)
    def _on_show_log_toggled(self, state):
        """Handles the Show Log checkbox state change."""
        is_checked = (state == Qt.CheckState.Checked.value)
        self.log_area.setVisible(is_checked)
        if is_checked:
            self.log_to_gui("Log display enabled.", level="DEBUG")
        else:
            self.log_to_gui("Log display disabled.", level="DEBUG")

    @Slot(int)
    def _on_announce_alerts_toggled(self, state):
        is_checked = (state == Qt.CheckState.Checked.value)
        if is_checked:
            self.log_to_gui("Alert announcements enabled.", level="INFO")
            self.update_status("Alert announcements enabled. Starting check cycle...")
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(100, self.perform_check_cycle)
        else:
            self.log_to_gui("Alert announcements disabled.", level="INFO")
            self.update_status("Alert announcements disabled. Timer paused.")
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            self.countdown_label.setText("Next check in: --:-- (Paused)")

    @Slot(str)
    def _on_interval_selected(self, selected_key):
        """Handles selection change in the interval Combobox."""
        new_interval_ms = CHECK_INTERVAL_OPTIONS.get(selected_key)
        if new_interval_ms is None or new_interval_ms == self.current_check_interval_ms:
            if new_interval_ms is None:
                self.log_to_gui(f"Invalid interval key selected: {selected_key}. No change.", level="WARNING")
            return

        self.current_check_interval_ms = new_interval_ms
        self.log_to_gui(
            f"Check interval changed to: {selected_key} ({self.current_check_interval_ms // 60000} minutes).",
            level="INFO")

        if self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.stop()
            self.log_to_gui(f"Restarting check cycle due to interval change.", level="DEBUG")
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(100, self.perform_check_cycle)
            self.update_status(
                f"Interval set to {selected_key}. Next check in ~{self.current_check_interval_ms // 60000} mins.")
        else:
            self.update_status(f"Interval set to {selected_key}. Announcements are paused.")

    def _fetch_station_coordinates(self, station_id, log_errors=True):
        """Fetches coordinates for a given NWS station ID (used for alerts)."""
        if not station_id:
            if log_errors: self.log_to_gui("Station ID is empty. Cannot fetch coordinates for alerts.", level="ERROR")
            return None
        station_url = NWS_STATION_API_URL_TEMPLATE.format(station_id=station_id.upper())
        headers = {'User-Agent': 'PyWeatherAlertGui/1.6 (your.email@example.com)',  # PLEASE CUSTOMIZE
                   'Accept': 'application/geo+json'}
        self.log_to_gui(f"Fetching coordinates for station {station_id} (for alerts) from {station_url}", level="DEBUG")
        try:
            response = requests.get(station_url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            geometry = data.get('geometry')
            if geometry and geometry.get('type') == 'Point':
                coordinates = geometry.get('coordinates')
                if coordinates and len(coordinates) == 2:
                    longitude, latitude = coordinates[0], coordinates[1]
                    self.log_to_gui(f"Coordinates for {station_id} (alerts): Lat={latitude}, Lon={longitude}",
                                    level="INFO")
                    return latitude, longitude
            if log_errors: self.log_to_gui(f"Could not parse coordinates from station data for {station_id} (alerts).",
                                           level="ERROR")
            return None
        except requests.exceptions.HTTPError as http_err:
            if log_errors:
                self.log_to_gui(f"HTTP error fetching station {station_id} (alerts): {http_err}", level="ERROR")
                if http_err.response and http_err.response.status_code == 404:
                    self.update_status(f"Error: Station ID '{station_id}' not found.")
                else:
                    self.update_status(f"Error: Could not get data for station '{station_id}'.")
            return None
        except requests.exceptions.RequestException as req_err:
            if log_errors:
                self.log_to_gui(f"Network error fetching station {station_id} (alerts): {req_err}", level="ERROR")
                self.update_status(f"Error: Network issue getting station data.")
            return None
        except ValueError:  # JSONDecodeError
            if log_errors:
                self.log_to_gui(f"Invalid JSON response for station {station_id} (alerts).", level="ERROR")
                self.update_status(f"Error: Invalid data from station API.")
            return None
        except Exception as e:
            if log_errors: self.log_to_gui(f"Unexpected error fetching coordinates for {station_id} (alerts): {e}",
                                           level="ERROR")
            return None

    # Removed _get_lat_lon_from_zip, _fetch_forecast_dwml, _format_dwml_forecast_display, _update_forecast_display

    def _get_current_weather_url(self, log_errors=True):  # For alerts
        """Constructs the weather alert URL using coordinates from the station ID."""
        station_id = self.station_id_entry.text().strip()
        if not station_id:
            if log_errors:
                self.log_to_gui("Station ID is empty. Cannot construct alert URL.", level="ERROR")
                self.update_status("Error: Station ID cannot be empty.")
            return None
        coordinates = self._fetch_station_coordinates(station_id, log_errors=log_errors)  # For alerts
        if coordinates:
            latitude, longitude = coordinates
            return f"{WEATHER_URL_PREFIX}{latitude}%2C{longitude}{WEATHER_URL_SUFFIX}"
        else:
            if log_errors: self.log_to_gui(
                f"Failed to get coordinates for station {station_id} (alerts). Cannot fetch alerts.", level="ERROR")
            return None

    def _get_alerts(self, url):
        """Fetches weather alerts from the provided URL for a specific point."""
        if not url: return []
        self.log_to_gui(f"Fetching alerts from {url}...", level="DEBUG")
        headers = {'User-Agent': 'PyWeatherAlertGui/1.6 (your.email@example.com)'}  # PLEASE CUSTOMIZE
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            self.log_to_gui(f"Successfully fetched {len(feed.entries)} entries from {url}.", level="DEBUG")
            return feed.entries
        except requests.exceptions.Timeout:
            self.log_to_gui(f"Timeout while trying to fetch alerts from {url}", level="ERROR")
        except requests.exceptions.HTTPError as http_err:
            status_code_info = f"Status code: {http_err.response.status_code}" if http_err.response else "Status code: N/A"
            self.log_to_gui(f"HTTP error occurred for {url}: {http_err} - {status_code_info}", level="ERROR")
        except requests.exceptions.RequestException as e:
            self.log_to_gui(f"Error fetching alerts from {url}: {e}", level="ERROR")
        except Exception as e:
            self.log_to_gui(f"An unexpected error occurred in _get_alerts ({url}): {e}", level="ERROR")
        return []

    def _speak_message_internal(self, text_to_speak, log_prefix="Spoken"):
        """Internal method to handle speaking and logging."""
        if not text_to_speak: return
        try:
            self.tts_engine.say(text_to_speak)
            self.tts_engine.runAndWait()  # This blocks the GUI
            self.log_to_gui(f"{log_prefix}: {text_to_speak}", level="INFO")
        except Exception as e:
            self.log_to_gui(f"Error during text-to-speech for '{text_to_speak}': {e}", level="ERROR")

    def _speak_weather_alert(self, alert_title, alert_summary):
        """Constructs and speaks the weather alert message, including current repeater info."""
        repeater_info = self.repeater_entry.text()
        message = f"Weather Alert: {alert_title}. Details: {alert_summary}"
        if repeater_info:
            if message and not message.endswith(('.', '!', '?')): message += "."
            message += f" {repeater_info}"
        self._speak_message_internal(message, log_prefix="Spoken Alert")

    def _speak_repeater_info(self):
        """Speaks the repeater information line from the GUI input."""
        repeater_text = self.repeater_entry.text()
        if repeater_text:
            self._speak_message_internal(repeater_text, log_prefix="Spoken")

    @Slot()
    def _on_speak_and_reset_button_press(self):
        """Handles the 'Speak Repeater Info & Reset Timer' button press."""
        self.log_to_gui("Speak & Reset Timer button pressed.", level="INFO")
        self._speak_repeater_info()

        if self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.stop()
            self.log_to_gui(f"Resetting alert announcement timer.", level="DEBUG")
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(100, self.perform_check_cycle)
            self.update_status(f"Manual speak & reset. Next check in ~{self.current_check_interval_ms // 60000} mins.")
        else:
            self.update_status("Repeater info spoken. Alert announcements are paused.")

    @Slot()
    def perform_check_cycle(self):
        """Performs one cycle of checking alerts, radar, and speaking."""
        if not self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            self.countdown_label.setText("Next check in: --:-- (Paused)")
            self.log_to_gui("Alert announcements are disabled. Skipping check cycle.", level="DEBUG")
            return

        self.main_check_timer.stop()
        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)

        # --- Update Radar ---
        if hasattr(self, 'web_view'):
            self.log_to_gui(f"Reloading radar view: {RADAR_URL}", level="DEBUG")
            self.web_view.setUrl(QUrl(RADAR_URL))

        # --- Removed Forecast Update ---

        # --- Check Alerts ---
        current_station_id = self.station_id_entry.text().strip()
        self.log_to_gui(f"Starting alert check for station: {current_station_id}", level="INFO")
        self.update_status(
            f"Checking for alerts for {current_station_id}... Last check: {time.strftime('%H:%M:%S')}")

        current_weather_alert_url = self._get_current_weather_url()  # For alerts
        alerts = []
        if current_weather_alert_url:
            alerts = self._get_alerts(current_weather_alert_url)
        else:
            self.log_to_gui("Skipping alert check as alert URL could not be determined.", level="WARNING")

        new_alerts_found_this_cycle = False
        if alerts:
            for alert in alerts:
                if not hasattr(alert, 'id') or not hasattr(alert, 'title') or not hasattr(alert, 'summary'):
                    self.log_to_gui(f"Skipping malformed alert entry: {alert}", level="WARNING")
                    continue
                if alert.id not in self.seen_alert_ids:
                    new_alerts_found_this_cycle = True
                    self.log_to_gui(f"New Weather Alert: {alert.title}", level="IMPORTANT")
                    if self.announce_alerts_checkbox.isChecked():
                        self._speak_weather_alert(alert.title, alert.summary)
                    self.seen_alert_ids.add(alert.id)

        if not new_alerts_found_this_cycle and current_weather_alert_url:
            self.log_to_gui(f"No new alerts in this cycle. Total unique alerts seen: {len(self.seen_alert_ids)}.",
                            level="INFO")

        if self.announce_alerts_checkbox.isChecked():
            self._speak_repeater_info()

        self.update_status(f"Check complete. Next check in ~{self.current_check_interval_ms // 60000} mins.")
        self.log_to_gui(f"Waiting for {self.current_check_interval_ms // 1000} seconds before next check.",
                        level="INFO")

        if self.current_check_interval_ms > 0 and self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.start(self.current_check_interval_ms)

    def closeEvent(self, event):
        """Handles graceful shutdown when the window is closed."""
        reply = QMessageBox.question(self, 'Quit',
                                     "Do you want to quit Weather Alert Monitor?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log_to_gui("Shutting down weather alert monitor...", level="INFO")
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            if hasattr(self.tts_engine, 'stop') and not self.is_tts_dummy:
                try:
                    if self.tts_engine.isBusy(): self.tts_engine.stop()
                except Exception as e:
                    logging.error(f"Error stopping TTS engine: {e}")
            event.accept()
        else:
            event.ignore()

if __name__ == "__main__":
    import pandas as pd # pgeocode uses pandas, good to have it explicitly if troubleshooting

    app = QApplication(sys.argv)
    main_win = WeatherAlertApp()
    main_win.show()
    sys.exit(app.exec())