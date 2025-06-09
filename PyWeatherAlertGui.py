import sys
import requests
import feedparser
import pyttsx3
import time
import logging
import os  # Import os module for path joining

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QMessageBox,
    QStatusBar, QCheckBox  # Added QCheckBox
)
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QTextCursor, QIcon

# --- Configuration ---
INITIAL_CHECK_INTERVAL_MS = 900 * 1000  # Default: 15 minutes

CHECK_INTERVAL_OPTIONS = {
    "1 Minute": 1 * 60 * 1000,
    "5 Minutes": 5 * 60 * 1000,
    "10 Minutes": 10 * 60 * 1000,
    "15 Minutes": 15 * 60 * 1000,
    "30 Minutes": 30 * 60 * 1000,
    "1 Hour": 60 * 60 * 1000,
}
DEFAULT_INTERVAL_KEY = "15 Minutes"

# Changed from LAT/LON to STATION_ID
DEFAULT_STATION_ID = "KSLO"  # Example Station ID
# NWS API endpoint for station details
NWS_STATION_API_URL_TEMPLATE = "https://api.weather.gov/stations/{station_id}"

WEATHER_URL_PREFIX = "https://api.weather.gov/alerts/active.atom?point="
WEATHER_URL_SUFFIX = "&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Future%2CExpected"
INITIAL_REPEATER_INFO = ""  # "Repeater, W S D R 5 3 8 Salem 550 Repeater"

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class WeatherAlertApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Weather Alert Monitor")
        self.setGeometry(100, 100, 700, 680) # Slightly increased height for checkbox

        # --- Set the Window Icon ---
        base_path = os.path.dirname(os.path.abspath(__file__))
        icon_path_png = os.path.join(base_path, "resources", "icon.png")
        icon_path_ico = os.path.join(base_path, "resources", "icon.ico")
        app_icon = QIcon()
        if os.path.exists(icon_path_png):
            app_icon.addFile(icon_path_png)
        elif os.path.exists(icon_path_ico):
            app_icon.addFile(icon_path_ico)
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
            logging.info("Application icon loaded successfully.")
        else:
            logging.warning("Could not load application icon from 'resources/icon.png' or 'resources/icon.ico'.")

        self.seen_alert_ids = set()
        self.tts_engine = self._initialize_tts_engine()
        self.is_tts_dummy = isinstance(self.tts_engine, self._DummyEngine)

        self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(DEFAULT_INTERVAL_KEY, INITIAL_CHECK_INTERVAL_MS)

        self.main_check_timer = QTimer(self)
        self.main_check_timer.timeout.connect(self.perform_check_cycle)

        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_countdown_display)
        self.remaining_time_seconds = 0

        self._init_ui() # This will now set the checkbox to unchecked

        if self.is_tts_dummy:
            self.log_to_gui(
                "TTS engine failed to initialize. Using fallback (logging to console/GUI instead of speaking).",
                level="ERROR")
        else:
            self.log_to_gui("TTS engine initialized successfully.", level="INFO")

        self.log_to_gui(
            f"Monitoring weather alerts for station: {self.station_id_entry.text()}",
            level="INFO")
        self.log_to_gui(f"Initial repeater line: '{self.repeater_entry.text()}'", level="INFO")
        self.log_to_gui(f"Initial check interval: {self.current_check_interval_ms // 60000} minutes.", level="INFO")

        # Initial state based on checkbox
        if self.announce_alerts_checkbox.isChecked(): # This will now be false initially
            self.log_to_gui("Alert announcements enabled by default.", level="INFO") # This log might be misleading now
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(1000, self.perform_check_cycle) # Start first check
        else:
            # This block will execute by default now
            self.log_to_gui("Alert announcements disabled by default. Check the box to start.", level="INFO")
            self.countdown_label.setText("Next check in: --:-- (Paused)")


    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Configuration Frame ---
        config_group = QWidget()
        config_layout = QGridLayout(config_group)
        config_layout.addWidget(QLabel("Repeater Info:"), 0, 0, Qt.AlignmentFlag.AlignLeft)
        self.repeater_entry = QLineEdit(INITIAL_REPEATER_INFO)
        config_layout.addWidget(self.repeater_entry, 0, 1, 1, 3)
        config_layout.addWidget(QLabel("NWS Station ID:"), 1, 0, Qt.AlignmentFlag.AlignLeft)
        self.station_id_entry = QLineEdit(DEFAULT_STATION_ID)
        self.station_id_entry.setFixedWidth(150)
        config_layout.addWidget(self.station_id_entry, 1, 1, Qt.AlignmentFlag.AlignLeft)
        config_layout.setColumnStretch(2, 1)
        main_layout.addWidget(config_group)

        # --- Controls Frame ---
        controls_group = QWidget()
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setContentsMargins(0,0,0,0)

        self.speak_reset_button = QPushButton("Speak Repeater Info & Reset Timer")
        self.speak_reset_button.clicked.connect(self._on_speak_and_reset_button_press)
        controls_layout.addWidget(self.speak_reset_button)

        # --- Announce Alerts Checkbox ---
        self.announce_alerts_checkbox = QCheckBox("Announce Alerts")
        self.announce_alerts_checkbox.setChecked(False) # <<< MODIFIED: Set to False for unchecked by default
        self.announce_alerts_checkbox.stateChanged.connect(self._on_announce_alerts_toggled)
        controls_layout.addWidget(self.announce_alerts_checkbox)
        # --- End Announce Alerts Checkbox ---

        controls_layout.addWidget(QLabel("Check Interval:"))
        self.interval_combobox = QComboBox()
        self.interval_combobox.addItems(CHECK_INTERVAL_OPTIONS.keys())
        self.interval_combobox.setCurrentText(DEFAULT_INTERVAL_KEY)
        self.interval_combobox.currentTextChanged.connect(self._on_interval_selected)
        controls_layout.addWidget(self.interval_combobox)

        controls_layout.addStretch(1)

        self.countdown_label = QLabel("Next check in: --:--")
        font = self.countdown_label.font()
        font.setPointSize(10)
        self.countdown_label.setFont(font)
        controls_layout.addWidget(self.countdown_label)
        main_layout.addWidget(controls_group)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        main_layout.addWidget(self.log_area, 1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        # Consider changing the initial status message if announcements are off by default
        self.update_status("Application started. Check 'Announce Alerts' to begin monitoring.")


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
        # Ensure the label reflects the paused state if the checkbox is off
        if not self.announce_alerts_checkbox.isChecked() and self.remaining_time_seconds <= 0 :
             self.countdown_label.setText("Next check in: --:-- (Paused)")
        else:
            self.countdown_label.setText(f"Next check in: {self._format_time(self.remaining_time_seconds)}")


    def _reset_and_start_countdown(self, total_seconds_for_interval):
        """Resets the countdown timer to the new interval and starts updating the display."""
        self.countdown_timer.stop()
        self.remaining_time_seconds = total_seconds_for_interval
        self.countdown_label.setText(f"Next check in: {self._format_time(self.remaining_time_seconds)}")
        if total_seconds_for_interval > 0 and self.announce_alerts_checkbox.isChecked(): # Only start if enabled
            self.countdown_timer.start(1000)
        elif not self.announce_alerts_checkbox.isChecked():
            self.countdown_label.setText("Next check in: --:-- (Paused)")


    @Slot(int) # state is an integer (0 for Unchecked, 2 for Checked)
    def _on_announce_alerts_toggled(self, state):
        is_checked = (state == Qt.CheckState.Checked.value) # Qt6 uses .value for enum comparison
        if is_checked:
            self.log_to_gui("Alert announcements enabled.", level="INFO")
            self.update_status("Alert announcements enabled. Starting check cycle...")
            # Reset countdown and start the main check cycle
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            # Perform a check almost immediately, which will then schedule subsequent checks
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

        if self.announce_alerts_checkbox.isChecked(): # Only restart timers if announcements are on
            self.main_check_timer.stop()
            self.log_to_gui(f"Restarting check cycle due to interval change.", level="DEBUG")
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(100, self.perform_check_cycle)
            self.update_status(
                f"Interval set to {selected_key}. Next check in ~{self.current_check_interval_ms // 60000} mins.")
        else:
            self.update_status(f"Interval set to {selected_key}. Announcements are paused.")


    def _fetch_station_coordinates(self, station_id, log_errors=True):
        """Fetches coordinates for a given NWS station ID."""
        if not station_id:
            if log_errors: self.log_to_gui("Station ID is empty. Cannot fetch coordinates.", level="ERROR")
            return None
        station_url = NWS_STATION_API_URL_TEMPLATE.format(station_id=station_id.upper())
        headers = {'User-Agent': 'PyWeatherAlertGui/1.1 (your.email@example.com)', 'Accept': 'application/geo+json'} # PLEASE CUSTOMIZE User-Agent
        self.log_to_gui(f"Fetching coordinates for station {station_id} from {station_url}", level="DEBUG")
        try:
            response = requests.get(station_url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            geometry = data.get('geometry')
            if geometry and geometry.get('type') == 'Point':
                coordinates = geometry.get('coordinates')
                if coordinates and len(coordinates) == 2:
                    longitude, latitude = coordinates[0], coordinates[1]
                    self.log_to_gui(f"Coordinates for {station_id}: Lat={latitude}, Lon={longitude}", level="INFO")
                    return latitude, longitude
            if log_errors: self.log_to_gui(f"Could not parse coordinates from station data for {station_id}.", level="ERROR")
            return None
        except requests.exceptions.HTTPError as http_err:
            if log_errors:
                self.log_to_gui(f"HTTP error fetching station {station_id}: {http_err}", level="ERROR")
                if http_err.response and http_err.response.status_code == 404: self.update_status(f"Error: Station ID '{station_id}' not found.")
                else: self.update_status(f"Error: Could not get data for station '{station_id}'.")
            return None
        except requests.exceptions.RequestException as req_err:
            if log_errors:
                self.log_to_gui(f"Network error fetching station {station_id}: {req_err}", level="ERROR")
                self.update_status(f"Error: Network issue getting station data.")
            return None
        except ValueError:
            if log_errors:
                self.log_to_gui(f"Invalid JSON response for station {station_id}.", level="ERROR")
                self.update_status(f"Error: Invalid data from station API.")
            return None
        except Exception as e:
            if log_errors: self.log_to_gui(f"Unexpected error fetching coordinates for {station_id}: {e}", level="ERROR")
            return None

    def _get_current_weather_url(self, log_errors=True):
        """Constructs the weather alert URL using coordinates from the station ID."""
        station_id = self.station_id_entry.text().strip()
        if not station_id:
            if log_errors:
                self.log_to_gui("Station ID is empty. Cannot construct alert URL.", level="ERROR")
                self.update_status("Error: Station ID cannot be empty.")
            return None
        coordinates = self._fetch_station_coordinates(station_id, log_errors=log_errors)
        if coordinates:
            latitude, longitude = coordinates
            return f"{WEATHER_URL_PREFIX}{latitude}%2C{longitude}{WEATHER_URL_SUFFIX}"
        else:
            if log_errors: self.log_to_gui(f"Failed to get coordinates for station {station_id}. Cannot fetch alerts.", level="ERROR")
            return None

    def _get_alerts(self, url):
        """Fetches weather alerts from the provided URL for a specific point."""
        if not url: return []
        self.log_to_gui(f"Fetching alerts from {url}...", level="DEBUG")
        headers = {'User-Agent': 'PyWeatherAlertGui/1.1 (your.email@example.com)'} # PLEASE CUSTOMIZE User-Agent
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            self.log_to_gui(f"Successfully fetched {len(feed.entries)} entries from {url}.", level="DEBUG")
            return feed.entries
        except requests.exceptions.Timeout: self.log_to_gui(f"Timeout while trying to fetch alerts from {url}", level="ERROR")
        except requests.exceptions.HTTPError as http_err:
            status_code_info = f"Status code: {http_err.response.status_code}" if http_err.response else "Status code: N/A"
            self.log_to_gui(f"HTTP error occurred for {url}: {http_err} - {status_code_info}", level="ERROR")
        except requests.exceptions.RequestException as e: self.log_to_gui(f"Error fetching alerts from {url}: {e}", level="ERROR")
        except Exception as e: self.log_to_gui(f"An unexpected error occurred in _get_alerts ({url}): {e}", level="ERROR")
        return []

    def _speak_message_internal(self, text_to_speak, log_prefix="Spoken"):
        """Internal method to handle speaking and logging."""
        if not text_to_speak: return
        try:
            self.tts_engine.say(text_to_speak)
            self.tts_engine.runAndWait() # This blocks the GUI
            self.log_to_gui(f"{log_prefix}: {text_to_speak}", level="INFO")
        except Exception as e: self.log_to_gui(f"Error during text-to-speech for '{text_to_speak}': {e}", level="ERROR")

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

        if self.announce_alerts_checkbox.isChecked(): # Only reset alert timer if announcements are on
            self.main_check_timer.stop()
            self.log_to_gui(f"Resetting alert announcement timer.", level="DEBUG")
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(100, self.perform_check_cycle)
            self.update_status(f"Manual speak & reset. Next check in ~{self.current_check_interval_ms // 60000} mins.")
        else:
            self.update_status("Repeater info spoken. Alert announcements are paused.")


    @Slot()
    def perform_check_cycle(self):
        """Performs one cycle of checking alerts and speaking."""
        if not self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.stop() # Ensure timer is stopped if checkbox got unchecked
            self.countdown_timer.stop()
            self.countdown_label.setText("Next check in: --:-- (Paused)")
            self.log_to_gui("Alert announcements are disabled. Skipping check cycle.", level="DEBUG")
            return

        self.main_check_timer.stop() # Stop timer before processing to avoid overlapping if processing is long
        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)

        current_station_id = self.station_id_entry.text().strip()
        self.log_to_gui(f"Starting new check cycle for station: {current_station_id}", level="INFO")
        self.update_status(f"Checking for alerts for {current_station_id}... Last check: {time.strftime('%H:%M:%S')}")

        current_weather_url = self._get_current_weather_url()
        alerts = []
        if current_weather_url:
            alerts = self._get_alerts(current_weather_url)
        else:
            self.log_to_gui("Skipping alert check as weather URL could not be determined.", level="WARNING")

        new_alerts_found_this_cycle = False
        if alerts:
            for alert in alerts:
                if not hasattr(alert, 'id') or not hasattr(alert, 'title') or not hasattr(alert, 'summary'):
                    self.log_to_gui(f"Skipping malformed alert entry: {alert}", level="WARNING")
                    continue
                if alert.id not in self.seen_alert_ids:
                    new_alerts_found_this_cycle = True
                    self.log_to_gui(f"New Weather Alert: {alert.title}", level="IMPORTANT")
                    if self.announce_alerts_checkbox.isChecked(): # Double check, though cycle shouldn't run if not
                        self._speak_weather_alert(alert.title, alert.summary)
                    self.seen_alert_ids.add(alert.id)

        if not new_alerts_found_this_cycle and current_weather_url:
            self.log_to_gui(f"No new alerts in this cycle. Total unique alerts seen: {len(self.seen_alert_ids)}.", level="INFO")

        # Speak repeater info at the end of the cycle, if announcements are generally on
        if self.announce_alerts_checkbox.isChecked():
            self._speak_repeater_info()

        self.update_status(f"Check complete. Next check in ~{self.current_check_interval_ms // 60000} mins.")
        self.log_to_gui(f"Waiting for {self.current_check_interval_ms // 1000} seconds before next check.", level="INFO")

        if self.current_check_interval_ms > 0 and self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.start(self.current_check_interval_ms) # Schedule next check

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
            self.log_to_gui(f"Cancelled main check timer on exit.", level="DEBUG")
            self.log_to_gui(f"Cancelled countdown timer on exit.", level="DEBUG")
            if hasattr(self.tts_engine, 'stop') and not self.is_tts_dummy:
                try:
                    if self.tts_engine.isBusy(): self.tts_engine.stop()
                except Exception as e: logging.error(f"Error stopping TTS engine: {e}")
            event.accept()
        else:
            event.ignore()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_win = WeatherAlertApp()
    main_win.show()
    sys.exit(app.exec())