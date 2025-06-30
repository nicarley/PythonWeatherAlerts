# PyWeatherAlertGui.py

import sys
import requests
import feedparser
import pyttsx3
import time
import logging
import os
import json
import shutil
import pandas
import pgeocode
from typing import Optional, Dict, Any, List, Tuple, Callable

# PySide6 imports
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QMessageBox,
    QStatusBar, QCheckBox, QSplitter, QStyleFactory, QGroupBox, QDialog,
    QDialogButtonBox, QFormLayout, QListWidget, QListWidgetItem, QLayout,
    QSpacerItem, QSizePolicy, QFileDialog, QFrame, QMenu, QStyle, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, QTimer, Slot, QUrl, QFile, QTextStream, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QTextCursor, QIcon, QColor, QDesktopServices, QPalette, QAction, QActionGroup, \
    QFont

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None
    logging.warning("PySide6.QtWebEngineWidgets not found. Web view will be disabled.")

# --- Application Version ---
versionnumber = "25.06.30"

# --- Constants ---
FALLBACK_INITIAL_CHECK_INTERVAL_MS = 900 * 1000
FALLBACK_DEFAULT_INTERVAL_KEY = "15 Minutes"
FALLBACK_DEFAULT_LOCATION_ID = "62881"  # Changed to a zip code for a more universal default
FALLBACK_INITIAL_REPEATER_INFO = ""
GITHUB_HELP_URL = "https://github.com/nicarley/PythonWeatherAlerts/wiki"

DEFAULT_RADAR_OPTIONS = {
    "N.W.S. Radar": "https://radar.weather.gov/",
    "Windy.com": "https://www.windy.com/",
}
FALLBACK_DEFAULT_RADAR_DISPLAY_NAME = "N.W.S. Radar"
FALLBACK_DEFAULT_RADAR_URL = DEFAULT_RADAR_OPTIONS[FALLBACK_DEFAULT_RADAR_DISPLAY_NAME]

FALLBACK_ANNOUNCE_ALERTS_CHECKED = False
FALLBACK_SHOW_LOG_CHECKED = False
FALLBACK_SHOW_ALERTS_AREA_CHECKED = True
FALLBACK_SHOW_FORECASTS_AREA_CHECKED = True
FALLBACK_AUTO_REFRESH_CONTENT_CHECKED = False
FALLBACK_DARK_MODE_ENABLED = False
FALLBACK_LOG_SORT_ORDER = "chronological"
FALLBACK_MUTE_AUDIO_CHECKED = False

CHECK_INTERVAL_OPTIONS = {
    "1 Minute": 1 * 60 * 1000, "5 Minutes": 5 * 60 * 1000,
    "10 Minutes": 10 * 60 * 1000, "15 Minutes": 15 * 60 * 1000,
    "30 Minutes": 30 * 60 * 1000, "1 Hour": 60 * 60 * 1000,
}

NWS_STATION_API_URL_TEMPLATE = "https://api.weather.gov/stations/{station_id}"
NWS_POINTS_API_URL_TEMPLATE = "https://api.weather.gov/points/{latitude},{longitude}"
# Modified WEATHER_URL_SUFFIX to include 'Immediate' urgency and remove 'Urgent' from severity
WEATHER_URL_PREFIX = "https://api.weather.gov/alerts/active.atom?point="
WEATHER_URL_SUFFIX = "&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Immediate%2CFuture%2CExpected"

SETTINGS_FILE_NAME = "settings.txt"
RESOURCES_FOLDER_NAME = "resources"
LIGHT_STYLESHEET_FILE_NAME = "modern.qss"
DARK_STYLESHEET_FILE_NAME = "dark_modern.qss"

ADD_NEW_SOURCE_TEXT = "Add New Source..."
MANAGE_SOURCES_TEXT = "Manage Sources..."
ADD_CURRENT_SOURCE_TEXT = "Add Current View as Source..."

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
IMPORTANT_LEVEL_NUM = logging.WARNING - 5
logging.addLevelName(IMPORTANT_LEVEL_NUM, "IMPORTANT")


def important(self, message, *args, **kws):
    if self.isEnabledFor(IMPORTANT_LEVEL_NUM):
        self._log(IMPORTANT_LEVEL_NUM, message, args, **kws)


logging.Logger.important = important


# --- Custom Exceptions ---
class ApiError(Exception):
    """Custom exception for API-related errors."""
    pass


# --- Helper Classes ---

class Worker(QRunnable):
    """
    Worker thread for executing long-running tasks without blocking the UI.
    Inherits from QRunnable to be used with QThreadPool.
    """

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = self.WorkerSignals()

    @Slot()
    def run(self):
        """Execute the work function and emit signals."""
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:
            self.signals.error.emit(e)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()

    class WorkerSignals(QObject):
        """Defines the signals available from a running worker thread."""
        finished = Signal()
        error = Signal(Exception)
        result = Signal(object)


class SettingsManager:
    """Handles loading and saving of application settings from a JSON file."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def load(self) -> Dict[str, Any]:
        """Loads settings from the JSON file."""
        if not os.path.exists(self.file_path):
            logging.warning(f"Settings file not found: {self.file_path}")
            return {}
        try:
            with open(self.file_path, 'r') as f:
                settings = json.load(f)
                logging.info(f"Settings loaded from {self.file_path}")
                return settings
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Error loading settings from {self.file_path}: {e}")
            return {}

    def save(self, settings: Dict[str, Any]) -> bool:
        """Saves settings to the JSON file."""
        try:
            with open(self.file_path, 'w') as f:
                json.dump(settings, f, indent=4)
            logging.info(f"Settings saved to {self.file_path}")
            return True
        except (IOError, OSError) as e:
            logging.error(f"Error saving settings to {self.file_path}: {e}")
            return False


class NwsApiClient:
    """Handles all network requests to the NWS API."""

    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.headers = {'User-Agent': self.user_agent, 'Accept': 'application/geo+json'}
        self.pgeocode_client = pgeocode.Nominatim('us')

    def get_coordinates_for_location(self, location_id: str) -> Optional[Tuple[float, float]]:
        """
        Tries to get coordinates for a given location input (zip or station ID).
        """
        if not location_id: return None
        processed_input = location_id.strip().upper()

        # Try as US Zip Code
        if processed_input.isdigit() and len(processed_input) == 5:
            location_info = self.pgeocode_client.query_postal_code(processed_input)
            if not location_info.empty and not pandas.isna(location_info.latitude):
                return location_info.latitude, location_info.longitude

        # Try as Airport/NWS Station ID
        nws_id_to_try = processed_input
        if len(processed_input) == 3 and processed_input.isalpha():
            nws_id_to_try = "K" + processed_input

        station_url = NWS_STATION_API_URL_TEMPLATE.format(station_id=nws_id_to_try)
        try:
            response = requests.get(station_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            coords = data.get('geometry', {}).get('coordinates')
            if coords and len(coords) == 2:
                return coords[1], coords[0]  # NWS is lon, lat; return lat, lon
        except requests.RequestException as e:
            logging.error(f"API error fetching station '{nws_id_to_try}': {e}")

        return None

    def get_forecast_urls(self, lat: float, lon: float) -> Optional[Dict[str, str]]:
        """Fetches gridpoint properties to get forecast URLs."""
        points_url = NWS_POINTS_API_URL_TEMPLATE.format(latitude=lat, longitude=lon)
        try:
            response = requests.get(points_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            props = response.json().get('properties', {})
            return {
                "hourly": props.get('forecastHourly'),
                "daily": props.get('forecast')
            }
        except (requests.RequestException, ValueError) as e:
            logging.error(f"API error fetching gridpoint properties: {e}")
            return None

    def get_forecast_data(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetches data from a specific forecast URL."""
        if not url: return None
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as e:
            logging.error(f"API error fetching forecast data from {url}: {e}")
            return None

    def get_alerts(self, lat: float, lon: float) -> List[Any]:
        """Fetches and parses weather alerts from the ATOM feed."""
        url = f"{WEATHER_URL_PREFIX}{lat}%2C{lon}{WEATHER_URL_SUFFIX}"
        try:
            response = requests.get(url, headers={'User-Agent': self.user_agent}, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            return feed.entries
        except requests.RequestException as e:
            logging.error(f"Error fetching alerts from {url}: {e}")
            return []


# --- Dialog Classes ---
class AboutDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("About Weather Alert Monitor")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        title_label = QLabel(f"<b>Weather Alert Monitor</b>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = title_label.font()
        title_font.setPointSize(16)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        version_label = QLabel(f"Version: {versionnumber} <br/>By: Nicolas Farley")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)
        layout.addSpacing(10)
        description_text = (
            "This application monitors National Weather Service (NWS) alerts "
            "for a specified location, displays current weather forecasts, "
            "and provides a web view for weather-related sites."
        )
        description_label = QLabel(description_text)
        description_label.setWordWrap(True)
        layout.addWidget(description_label)
        layout.addSpacing(10)
        github_link_label = QLabel()
        github_link_label.setTextFormat(Qt.TextFormat.RichText)
        github_link_label.setText(
            f'For more information, visit the <a href="{GITHUB_HELP_URL}">project page on GitHub</a>.'
        )
        github_link_label.setOpenExternalLinks(True)
        github_link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(github_link_label)
        layout.addSpacing(15)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box, alignment=Qt.AlignmentFlag.AlignCenter)
        self.setLayout(layout)


class AddEditSourceDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, current_name: Optional[str] = None,
                 current_url: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Web Source" if current_name else "Add New Web Source")
        self.layout = QFormLayout(self)
        self.name_edit = QLineEdit(self)
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("https://example.com")
        if current_name: self.name_edit.setText(current_name)
        if current_url: self.url_edit.setText(current_url)
        self.layout.addRow("Display Name:", self.name_edit)
        self.layout.addRow("URL:", self.url_edit)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        Qt.Orientation.Horizontal, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_data(self) -> Optional[Tuple[str, str]]:
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        if name and url and (url.startswith("http://") or url.startswith("https://")):
            return name, url
        QMessageBox.warning(self, "Invalid Input",
                            "Please provide a valid name and a URL starting with http:// or https://.")
        return None


class ManageSourcesDialog(QDialog):
    def __init__(self, sources: Dict[str, str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Manage Web Sources")
        # Store sources internally as a list of (name, url) tuples to preserve order
        self.sources_list: List[Tuple[str, str]] = list(sources.items())
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        # Populate list widget from the list of tuples
        for name, _ in self.sources_list:
            self.list_widget.addItem(name)
        layout.addWidget(self.list_widget)

        button_layout = QHBoxLayout()
        add_button = QPushButton("Add...")
        add_button.clicked.connect(self.add_source)
        edit_button = QPushButton("Edit...")
        edit_button.clicked.connect(self.edit_source)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self.remove_source)

        # New Move Up/Down buttons
        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(self.move_up_source)
        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(self.move_down_source)

        button_layout.addWidget(add_button)
        button_layout.addWidget(edit_button)
        button_layout.addWidget(remove_button)
        button_layout.addStretch() # Add stretch to push move buttons to the right
        button_layout.addWidget(move_up_button)
        button_layout.addWidget(move_down_button)
        layout.addLayout(button_layout)

        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)

    def add_source(self):
        dialog = AddEditSourceDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data: return
            name, url = data
            # Check for duplicate name in the current list
            if any(n == name for n, _ in self.sources_list):
                QMessageBox.warning(self, "Duplicate Name", f"A source with the name '{name}' already exists.")
                return
            self.sources_list.append((name, url)) # Add to internal list
            self.list_widget.addItem(name) # Add to QListWidget
            self.list_widget.setCurrentRow(len(self.sources_list) - 1) # Select the newly added item

    def edit_source(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item:
            return
        current_row = self.list_widget.currentRow()
        old_name, old_url = self.sources_list[current_row] # Get from internal list

        dialog = AddEditSourceDialog(self, current_name=old_name, current_url=old_url)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data: return
            new_name, new_url = data

            # Check for duplicate name if name changed, excluding the current item
            if new_name != old_name and any(n == new_name for i, (n, _) in enumerate(self.sources_list) if i != current_row):
                QMessageBox.warning(self, "Duplicate Name", f"A source with the name '{new_name}' already exists.")
                return

            self.sources_list[current_row] = (new_name, new_url) # Update internal list
            selected_item.setText(new_name) # Update QListWidgetItem text

    def remove_source(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item:
            return
        current_row = self.list_widget.currentRow()
        name_to_remove = self.sources_list[current_row][0] # Get name from internal list

        reply = QMessageBox.question(self, "Confirm Removal", f"Are you sure you want to remove '{name_to_remove}'?")
        if reply == QMessageBox.StandardButton.Yes:
            self.sources_list.pop(current_row) # Remove from internal list
            self.list_widget.takeItem(current_row) # Remove from QListWidget

    def move_up_source(self):
        current_row = self.list_widget.currentRow()
        if current_row > 0: # Can move up if not the first item
            # Update internal list
            item_to_move = self.sources_list.pop(current_row)
            self.sources_list.insert(current_row - 1, item_to_move)

            # Update QListWidget
            q_item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row - 1, q_item)
            self.list_widget.setCurrentRow(current_row - 1) # Keep selection on the moved item

    def move_down_source(self):
        current_row = self.list_widget.currentRow()
        if current_row < len(self.sources_list) - 1: # Can move down if not the last item
            # Update internal list
            item_to_move = self.sources_list.pop(current_row)
            self.sources_list.insert(current_row + 1, item_to_move)

            # Update QListWidget
            q_item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row + 1, q_item)
            self.list_widget.setCurrentRow(current_row + 1) # Keep selection on the moved item

    def get_sources(self) -> Dict[str, str]:
        # Convert the internal list of tuples back to a dictionary for external use
        # Python dictionaries (since 3.7) preserve insertion order, so this will maintain the order.
        return dict(self.sources_list)


class SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, current_settings: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.current_settings = current_settings if current_settings else {}

        main_layout = QVBoxLayout(self)

        # --- General Settings ---
        general_group = QGroupBox("General")
        form_layout = QFormLayout(general_group)

        self.repeater_entry = QLineEdit(self.current_settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO))
        form_layout.addRow("Repeater Announcement:", self.repeater_entry)

        self.location_id_entry = QLineEdit(self.current_settings.get("location_id", FALLBACK_DEFAULT_LOCATION_ID))
        self.location_id_entry.setFixedWidth(150)
        location_id_layout = QHBoxLayout()
        location_id_layout.addWidget(self.location_id_entry)
        airport_lookup_label = QLabel(
            '<a href="https://www.iata.org/en/publications/directories/code-search/">Airport ID Lookup</a>')
        airport_lookup_label.setOpenExternalLinks(True)
        location_id_layout.addWidget(airport_lookup_label)
        location_id_layout.addStretch()
        form_layout.addRow("Location (US Zip/Airport ID):", location_id_layout)

        self.interval_combobox = QComboBox()
        self.interval_combobox.addItems(CHECK_INTERVAL_OPTIONS.keys())
        self.interval_combobox.setCurrentText(self.current_settings.get("interval_key", FALLBACK_DEFAULT_INTERVAL_KEY))
        form_layout.addRow("Check Interval:", self.interval_combobox)

        main_layout.addWidget(general_group)

        # --- Behavior & Display Settings ---
        behavior_group = QGroupBox("Behavior & Display")
        behavior_form_layout = QFormLayout(behavior_group) # Use QFormLayout for alignment

        self.announce_alerts_check = QCheckBox("Announce Alerts and Start Timer")
        self.announce_alerts_check.setChecked(self.current_settings.get("announce_alerts", FALLBACK_ANNOUNCE_ALERTS_CHECKED))
        behavior_form_layout.addRow(self.announce_alerts_check)

        self.auto_refresh_check = QCheckBox("Auto-Refresh Web Content")
        self.auto_refresh_check.setChecked(self.current_settings.get("auto_refresh_content", FALLBACK_AUTO_REFRESH_CONTENT_CHECKED))
        behavior_form_layout.addRow(self.auto_refresh_check)

        self.mute_audio_check = QCheckBox("Mute All Audio")
        self.mute_audio_check.setChecked(self.current_settings.get("mute_audio", FALLBACK_MUTE_AUDIO_CHECKED))
        behavior_form_layout.addRow(self.mute_audio_check)

        self.dark_mode_check = QCheckBox("Enable Dark Mode")
        self.dark_mode_check.setChecked(self.current_settings.get("dark_mode_enabled", FALLBACK_DARK_MODE_ENABLED))
        behavior_form_layout.addRow(self.dark_mode_check)

        behavior_form_layout.addRow(QFrame(frameShape=QFrame.Shape.HLine, frameShadow=QFrame.Shadow.Sunken))

        self.show_log_check = QCheckBox("Show Log Panel on Startup")
        self.show_log_check.setToolTip("Show or hide the log panel at the bottom of the window.")
        self.show_log_check.setChecked(self.current_settings.get("show_log", FALLBACK_SHOW_LOG_CHECKED))
        behavior_form_layout.addRow(self.show_log_check)

        self.show_alerts_check = QCheckBox("Show Current Alerts Area on Startup")
        self.show_alerts_check.setToolTip("Show or hide the Current Alerts panel.")
        self.show_alerts_check.setChecked(self.current_settings.get("show_alerts_area", FALLBACK_SHOW_ALERTS_AREA_CHECKED))
        behavior_form_layout.addRow(self.show_alerts_check)

        self.show_forecasts_check = QCheckBox("Show Weather Forecast Area on Startup")
        self.show_forecasts_check.setToolTip("Show or hide the Weather Forecast panel.")
        self.show_forecasts_check.setChecked(self.current_settings.get("show_forecasts_area", FALLBACK_SHOW_FORECASTS_AREA_CHECKED))
        behavior_form_layout.addRow(self.show_forecasts_check)

        behavior_form_layout.addRow(QFrame(frameShape=QFrame.Shape.HLine, frameShadow=QFrame.Shadow.Sunken))

        self.log_sort_combo = QComboBox()
        self.log_sort_combo.addItems(["Chronological", "Ascending", "Descending"])
        self.log_sort_combo.setCurrentText(self.current_settings.get("log_sort_order", FALLBACK_LOG_SORT_ORDER).capitalize())
        behavior_form_layout.addRow("Initial Log Sort Order:", self.log_sort_combo)

        main_layout.addWidget(behavior_group)

        # --- Dialog Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def get_settings_data(self) -> Dict[str, Any]:
        return {
            # General
            "repeater_info": self.repeater_entry.text(),
            "location_id": self.location_id_entry.text().strip().upper(),
            "interval_key": self.interval_combobox.currentText(),
            # Behavior & Display
            "announce_alerts": self.announce_alerts_check.isChecked(),
            "auto_refresh_content": self.auto_refresh_check.isChecked(),
            "mute_audio": self.mute_audio_check.isChecked(),
            "dark_mode_enabled": self.dark_mode_check.isChecked(),
            "show_log": self.show_log_check.isChecked(),
            "show_alerts_area": self.show_alerts_check.isChecked(),
            "show_forecasts_area": self.show_forecasts_check.isChecked(),
            "log_sort_order": self.log_sort_combo.currentText().lower(),
        }


# --- Main Application Window ---
class WeatherAlertApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Weather Alert Monitor v{versionnumber}")
        self.setGeometry(100, 100, 950, 850)

        self._log_buffer: List[str] = []

        self.api_client = NwsApiClient(f'PyWeatherAlertGui/{versionnumber} (github.com/nicarley/PythonWeatherAlerts)')
        self.settings_manager = SettingsManager(os.path.join(self._get_resources_path(), SETTINGS_FILE_NAME))
        self.thread_pool = QThreadPool()
        self.log_to_gui(f"Multithreading with up to {self.thread_pool.maxThreadCount()} threads.", level="DEBUG")

        self.current_coords: Optional[Tuple[float, float]] = None

        # Initialize application state variables
        self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()
        self._last_valid_radar_text = FALLBACK_DEFAULT_RADAR_DISPLAY_NAME
        self.current_radar_url = FALLBACK_DEFAULT_RADAR_URL
        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.current_location_id = FALLBACK_DEFAULT_LOCATION_ID
        self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
        self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
        self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED
        self.current_show_alerts_area_checked = FALLBACK_SHOW_ALERTS_AREA_CHECKED
        self.current_show_forecasts_area_checked = FALLBACK_SHOW_FORECASTS_AREA_CHECKED
        self.current_auto_refresh_content_checked = FALLBACK_AUTO_REFRESH_CONTENT_CHECKED
        self.current_dark_mode_enabled = FALLBACK_DARK_MODE_ENABLED
        self.current_log_sort_order = FALLBACK_LOG_SORT_ORDER
        self.current_mute_audio_checked = FALLBACK_MUTE_AUDIO_CHECKED

        self._load_settings()
        self._set_window_icon()

        self.seen_alert_ids = set()
        self.tts_engine = self._initialize_tts_engine()
        self.is_tts_dummy = isinstance(self.tts_engine, self._DummyEngine)

        self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
            self.current_interval_key, FALLBACK_INITIAL_CHECK_INTERVAL_MS)

        self.main_check_timer = QTimer(self)
        self.main_check_timer.timeout.connect(self.perform_check_cycle)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_countdown_display)
        self.remaining_time_seconds = 0

        self._init_ui()
        self._apply_loaded_settings_to_ui()

        self.log_to_gui(f"Monitoring Location: {self.current_location_id}", level="INFO")
        self._update_location_data()  # Initial fetch for coords, alerts, and forecasts
        self._update_main_timer_state()

    def _set_window_icon(self):
        """Sets the application window icon, trying custom files first."""
        icon_path_ico = os.path.join(self._get_resources_path(), "icon.ico")
        icon_path_png = os.path.join(self._get_resources_path(), "icon.png")

        if os.path.exists(icon_path_ico):
            icon = QIcon(icon_path_ico)
            self.log_to_gui(f"Loaded application icon from: {icon_path_ico}", level="DEBUG")
        elif os.path.exists(icon_path_png):
            icon = QIcon(icon_path_png)
            self.log_to_gui(f"Loaded application icon from: {icon_path_png}", level="DEBUG")
        else:
            # Fallback to a standard PySide6 icon if custom files are not found
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
            self.log_to_gui("Custom application icon not found. Using default PySide6 icon.", level="WARNING")

        self.setWindowIcon(icon)

    def _get_resources_path(self) -> str:
        base_path = os.path.dirname(os.path.abspath(__file__))
        resources_path = os.path.join(base_path, RESOURCES_FOLDER_NAME)
        os.makedirs(resources_path, exist_ok=True)
        return resources_path

    def _load_settings(self):
        settings = self.settings_manager.load()
        if not settings:
            self._apply_fallback_settings("Settings file not found or invalid. Using defaults.")
            return

        self.current_repeater_info = settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO)
        self.current_location_id = settings.get("location_id", FALLBACK_DEFAULT_LOCATION_ID)
        self.current_interval_key = settings.get("check_interval_key", FALLBACK_DEFAULT_INTERVAL_KEY)
        self.RADAR_OPTIONS = settings.get("radar_options_dict", DEFAULT_RADAR_OPTIONS.copy())
        self.current_radar_url = settings.get("radar_url", FALLBACK_DEFAULT_RADAR_URL)
        self.current_announce_alerts_checked = settings.get("announce_alerts", FALLBACK_ANNOUNCE_ALERTS_CHECKED)
        self.current_show_log_checked = settings.get("show_log", FALLBACK_SHOW_LOG_CHECKED)
        self.current_show_alerts_area_checked = settings.get("show_alerts_area", FALLBACK_SHOW_ALERTS_AREA_CHECKED)
        self.current_show_forecasts_area_checked = settings.get("show_forecasts_area",
                                                                FALLBACK_SHOW_FORECASTS_AREA_CHECKED)
        self.current_auto_refresh_content_checked = settings.get("auto_refresh_content",
                                                                 FALLBACK_AUTO_REFRESH_CONTENT_CHECKED)
        self.current_dark_mode_enabled = settings.get("dark_mode_enabled", FALLBACK_DARK_MODE_ENABLED)
        self.current_log_sort_order = settings.get("log_sort_order", FALLBACK_LOG_SORT_ORDER)
        self.current_mute_audio_checked = settings.get("mute_audio", FALLBACK_MUTE_AUDIO_CHECKED)

        self._last_valid_radar_text = self._get_display_name_for_url(self.current_radar_url) or \
                                      (list(self.RADAR_OPTIONS.keys())[0] if self.RADAR_OPTIONS else "")

    def _apply_fallback_settings(self, reason_message: str):
        self.log_to_gui(reason_message, level="WARNING")
        # Reset all settings to their fallback values
        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.current_location_id = FALLBACK_DEFAULT_LOCATION_ID
        self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
        self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()
        self.current_radar_url = FALLBACK_DEFAULT_RADAR_URL
        self._last_valid_radar_text = FALLBACK_DEFAULT_RADAR_DISPLAY_NAME
        self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
        self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED
        self.current_show_alerts_area_checked = FALLBACK_SHOW_ALERTS_AREA_CHECKED
        self.current_show_forecasts_area_checked = FALLBACK_SHOW_FORECASTS_AREA_CHECKED
        self.current_auto_refresh_content_checked = FALLBACK_AUTO_REFRESH_CONTENT_CHECKED
        self.current_dark_mode_enabled = FALLBACK_DARK_MODE_ENABLED
        self.current_log_sort_order = FALLBACK_LOG_SORT_ORDER
        self.current_mute_audio_checked = FALLBACK_MUTE_AUDIO_CHECKED

    @Slot()
    def _save_settings(self):
        settings = {
            "repeater_info": self.current_repeater_info,
            "location_id": self.current_location_id,
            "check_interval_key": self.current_interval_key,
            "radar_options_dict": self.RADAR_OPTIONS,
            "radar_url": self.current_radar_url,
            "announce_alerts": self.announce_alerts_action.isChecked(),
            "auto_refresh_content": self.auto_refresh_action.isChecked(),
            "mute_audio": self.mute_action.isChecked(),
            "dark_mode_enabled": self.dark_mode_action.isChecked(),
            "show_log": self.show_log_action.isChecked(),
            "show_alerts_area": self.show_alerts_area_action.isChecked(),
            "show_forecasts_area": self.show_forecasts_area_action.isChecked(),
            "log_sort_order": self.current_log_sort_order,
        }
        if self.settings_manager.save(settings):
            self.update_status("Settings saved.")
        else:
            self.log_to_gui("Error saving settings.", level="ERROR")
            QMessageBox.critical(self, "Error", "Could not save settings to file.")

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)

        # --- Top Status Bar ---
        top_status_layout = self._create_top_status_bar()
        main_layout.addLayout(top_status_layout)

        # --- Menu Bar ---
        self._create_menu_bar()

        # --- Main Content Area ---
        alerts_forecasts_layout = QHBoxLayout()

        # Alerts Group
        self.alerts_group = QGroupBox("Current Alerts")
        alerts_layout = QVBoxLayout(self.alerts_group)
        self.alerts_display_area = QListWidget()
        self.alerts_display_area.setObjectName("AlertsDisplayArea")
        self.alerts_display_area.setWordWrap(True)
        self.alerts_display_area.setAlternatingRowColors(True)
        alerts_layout.addWidget(self.alerts_display_area)
        alerts_forecasts_layout.addWidget(self.alerts_group, 1)  # Stretch 1 for alerts

        # Combined Forecasts Group (main container for all forecasts)
        self.combined_forecast_widget = QGroupBox("Weather Forecast")
        # Changed to QHBoxLayout to place hourly and daily side-by-side
        combined_forecast_main_layout = QHBoxLayout(self.combined_forecast_widget)
        combined_forecast_main_layout.setContentsMargins(5, 5, 5, 5)  # Add some margins to the main forecast box

        # Hourly Forecast Sub-Group
        hourly_forecast_sub_group = QGroupBox("8-Hour Forecast")  # New QGroupBox for hourly
        hourly_forecast_sub_group_layout = QVBoxLayout(hourly_forecast_sub_group)
        hourly_forecast_sub_group_layout.setContentsMargins(5, 5, 5, 5)  # Margins for the sub-group box
        self.hourly_forecast_widget = QWidget()  # This widget holds the QGridLayout
        self.hourly_forecast_layout = QGridLayout(self.hourly_forecast_widget)
        self.hourly_forecast_layout.setContentsMargins(5, 5, 5, 5)  # Margins for the grid itself
        self.hourly_forecast_layout.setSpacing(5)  # Spacing between cells

        # Set font for the hourly forecast content
        hourly_font = QFont()
        hourly_font.setPointSize(9)  # A common readable size for table-like data
        self.hourly_forecast_widget.setFont(hourly_font)

        hourly_forecast_sub_group_layout.addWidget(self.hourly_forecast_widget)
        combined_forecast_main_layout.addWidget(hourly_forecast_sub_group, 1)  # Stretch 1 for hourly sub-group

        # Daily Forecast Sub-Group
        daily_forecast_sub_group = QGroupBox("5-Day Forecast")  # New QGroupBox for daily
        daily_forecast_sub_group_layout = QVBoxLayout(daily_forecast_sub_group)
        daily_forecast_sub_group_layout.setContentsMargins(5, 5, 5, 5)  # Margins for the sub-group box
        self.daily_forecast_widget = QWidget()  # This widget holds the QGridLayout
        self.daily_forecast_layout = QGridLayout(self.daily_forecast_widget)
        self.daily_forecast_layout.setContentsMargins(5, 5, 5, 5)  # Margins for the grid itself
        self.daily_forecast_layout.setSpacing(5)  # Spacing between cells

        # Set font for the daily forecast content
        daily_font = QFont()
        daily_font.setPointSize(9)  # Same size for consistency
        self.daily_forecast_widget.setFont(daily_font)

        daily_forecast_sub_group_layout.addWidget(self.daily_forecast_widget)
        combined_forecast_main_layout.addWidget(daily_forecast_sub_group, 1)  # Stretch 1 for daily sub-group

        alerts_forecasts_layout.addWidget(self.combined_forecast_widget,
                                          2)  # Stretch 2 for the main combined forecasts group

        # Add the alerts/forecasts layout to the main layout
        main_layout.addLayout(alerts_forecasts_layout, 1)  # Stretch 1 for this whole top section

        # --- Splitter for Web View and Log ---
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        if QWebEngineView:
            self.web_view = QWebEngineView()
            self.splitter.addWidget(self.web_view)
        else:
            self.web_view = QLabel("WebEngineView not available. Please install 'PySide6-WebEngine'.")
            self.web_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.splitter.addWidget(self.web_view)

        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_toolbar = QHBoxLayout()
        log_toolbar.addWidget(QLabel("<b>Application Log</b>"))
        log_toolbar.addStretch()

        # Add sorting buttons
        style = self.style()
        sort_asc_button = QPushButton("Sort Asc")
        sort_asc_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        sort_asc_button.setToolTip("Sort log ascending (A-Z)")
        sort_asc_button.clicked.connect(self._sort_log_ascending)
        log_toolbar.addWidget(sort_asc_button)

        sort_desc_button = QPushButton("Sort Desc")
        sort_desc_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        sort_desc_button.setToolTip("Sort log descending (Z-A)")
        sort_desc_button.clicked.connect(self._sort_log_descending)
        log_toolbar.addWidget(sort_desc_button)

        clear_log_button = QPushButton("Clear Log")
        clear_log_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton))
        clear_log_button.clicked.connect(lambda: self.log_area.clear())
        log_toolbar.addWidget(clear_log_button)

        log_layout.addLayout(log_toolbar)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        log_layout.addWidget(self.log_area)
        self.splitter.addWidget(log_widget)

        # Flush any buffered log messages
        if self._log_buffer:
            self.log_area.append("\n".join(self._log_buffer))
            self._log_buffer.clear()

        self.splitter.setSizes([400, 200])
        # Add the splitter with a larger stretch factor to make it take up more space
        main_layout.addWidget(self.splitter, 3)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # --- Network Status Indicator ---
        self.network_status_indicator = QLabel("● Network OK")
        self.network_status_indicator.setStyleSheet("color: green; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.network_status_indicator)
        # ---

        self.update_status("Application started.")

    def _create_top_status_bar(self) -> QHBoxLayout:
        """Creates and returns the layout for the top status bar."""
        top_status_layout = QHBoxLayout()
        top_status_layout.setContentsMargins(5, 3, 5, 3)

        style = self.style()
        self.top_repeater_label = QLabel("Repeater: N/A")
        self.top_countdown_label = QLabel("Next Check: --:--")
        self.current_time_label = QLabel("Current Time: --:--:--")

        # Volume Icon
        volume_icon_label = QLabel()
        volume_icon_label.setPixmap(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume).pixmap(16, 16))
        top_status_layout.addWidget(volume_icon_label)
        top_status_layout.addWidget(self.top_repeater_label)
        top_status_layout.addSpacing(20)

        # Location
        location_icon_label = QLabel()
        location_icon_label.setPixmap(style.standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon).pixmap(16, 16))
        top_status_layout.addWidget(location_icon_label)

        self.top_location_edit = QLineEdit()
        self.top_location_edit.setPlaceholderText("Zip/Airport ID")
        self.top_location_edit.setFixedWidth(100)  # Adjust as needed
        self.top_location_edit.setToolTip("Enter US Zip Code or NWS Airport ID (e.g., KSTL)")
        top_status_layout.addWidget(self.top_location_edit)

        self.location_apply_button = QPushButton("Apply")
        self.location_apply_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self.location_apply_button.setToolTip("Apply location change")
        self.location_apply_button.clicked.connect(self._on_top_location_apply_clicked)
        top_status_layout.addWidget(self.location_apply_button)
        top_status_layout.addSpacing(20)

        # Interval
        interval_icon_label = QLabel()
        interval_icon_label.setPixmap(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload).pixmap(16, 16))
        top_status_layout.addWidget(interval_icon_label)

        self.top_interval_combo = QComboBox()
        self.top_interval_combo.addItems(CHECK_INTERVAL_OPTIONS.keys())
        self.top_interval_combo.setToolTip("Set check interval")
        self.top_interval_combo.currentTextChanged.connect(self._on_top_interval_changed)
        top_status_layout.addWidget(self.top_interval_combo)
        top_status_layout.addSpacing(10)

        self.web_source_quick_select_button = QPushButton("Web Source")
        self.web_source_quick_select_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.web_source_quick_select_button.setToolTip("Quick select web source")
        self.web_source_quick_select_button.clicked.connect(self._show_web_source_quick_select_menu)
        top_status_layout.addWidget(self.web_source_quick_select_button)

        # --- Add Mute Button ---
        self.mute_button = QPushButton("Mute")
        self.mute_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted))
        self.mute_button.setToolTip("Mute All Audio")
        self.mute_button.setCheckable(True)
        self.mute_button.toggled.connect(self._on_mute_toggled)
        top_status_layout.addWidget(self.mute_button)
        # ---

        top_status_layout.addStretch(1)
        top_status_layout.addWidget(self.top_countdown_label)
        top_status_layout.addSpacing(15)
        top_status_layout.addWidget(self.current_time_label)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_current_time_display)
        self.clock_timer.start(1000)
        self._update_current_time_display()
        return top_status_layout

    def _create_menu_bar(self):
        """Creates the main menu bar with actions and icons."""
        menu_bar = self.menuBar()
        style = self.style()

        # File Menu
        file_menu = menu_bar.addMenu("&File")
        preferences_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
                                     "&Preferences...", self)
        preferences_action.triggered.connect(self._open_preferences_dialog)
        file_menu.addAction(preferences_action)
        file_menu.addSeparator()
        self.backup_settings_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
                                              "&Backup Settings...", self)
        self.backup_settings_action.triggered.connect(self._backup_settings)
        file_menu.addAction(self.backup_settings_action)
        self.restore_settings_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOkButton),
                                               "&Restore Settings...", self)
        self.restore_settings_action.triggered.connect(self._restore_settings)
        file_menu.addAction(self.restore_settings_action)
        file_menu.addSeparator()
        exit_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton), "E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View Menu
        view_menu = menu_bar.addMenu("&View")
        self.web_sources_menu = view_menu.addMenu("&Web Sources")
        self.web_sources_menu.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        view_menu.addSeparator()
        self.show_log_action = QAction("Show &Log Panel", self, checkable=True)
        self.show_log_action.toggled.connect(self._on_show_log_toggled)
        view_menu.addAction(self.show_log_action)
        self.show_alerts_area_action = QAction("Show Current &Alerts Area", self, checkable=True)
        self.show_alerts_area_action.toggled.connect(self._on_show_alerts_toggled)
        view_menu.addAction(self.show_alerts_area_action)
        self.show_forecasts_area_action = QAction("Show Station &Forecasts Area", self, checkable=True)
        self.show_forecasts_area_action.toggled.connect(self._on_show_forecasts_toggled)
        view_menu.addAction(self.show_forecasts_area_action)
        view_menu.addSeparator()
        self.dark_mode_action = QAction("&Enable Dark Mode", self, checkable=True)
        self.dark_mode_action.toggled.connect(self._on_dark_mode_toggled)
        view_menu.addAction(self.dark_mode_action)

        # Actions Menu
        actions_menu = menu_bar.addMenu("&Actions")
        self.announce_alerts_action = QAction("&Announce Alerts and Start Timer", self, checkable=True)
        self.announce_alerts_action.toggled.connect(self._on_announce_alerts_toggled)
        actions_menu.addAction(self.announce_alerts_action)
        self.auto_refresh_action = QAction("Auto-&Refresh Content", self, checkable=True)
        self.auto_refresh_action.toggled.connect(self._on_auto_refresh_content_toggled)
        actions_menu.addAction(self.auto_refresh_action)
        self.mute_action = QAction("Mute All Audio", self, checkable=True)
        self.mute_action.toggled.connect(self._on_mute_toggled)
        actions_menu.addAction(self.mute_action)
        actions_menu.addSeparator()
        self.speak_reset_action = QAction("&Speak Repeater Info and Reset Timer", self)
        self.speak_reset_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.speak_reset_action.triggered.connect(self._on_speak_and_reset_button_press)
        actions_menu.addAction(self.speak_reset_action)

        # Help Menu
        help_menu = menu_bar.addMenu("&Help")
        github_help_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxQuestion),
                                     "View Help on GitHub", self)
        github_help_action.triggered.connect(self._show_github_help)
        help_menu.addAction(github_help_action)
        help_menu.addSeparator()
        about_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation), "&About...", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _update_location_data(self):
        """
        Fetches all data for the current location (coords, alerts, forecasts)
        in a background thread.
        """
        self.update_status(f"Fetching data for {self.current_location_id}...")
        self._clear_and_set_loading_states()

        worker = Worker(self._fetch_all_data_for_location, self.current_location_id)
        worker.signals.result.connect(self._on_location_data_loaded)
        worker.signals.error.connect(self._on_data_load_error)
        self.thread_pool.start(worker)

    def _fetch_all_data_for_location(self, location_id: str) -> Dict[str, Any]:
        """Worker function to be run in a background thread."""
        coords = self.api_client.get_coordinates_for_location(location_id)
        if not coords:
            # This already raises ValueError, which is caught by Worker.signals.error
            raise ValueError(f"Could not find coordinates for location '{location_id}'.")

        lat, lon = coords

        # Fetch alerts (empty list is acceptable if no alerts)
        alerts = self.api_client.get_alerts(lat, lon)

        # Fetch forecast URLs - critical for forecasts
        forecast_urls = self.api_client.get_forecast_urls(lat, lon)
        if not forecast_urls:
            raise ApiError(f"Could not retrieve forecast URLs for {lat},{lon}. API might be down or rate-limited.")

        hourly_forecast = None
        daily_forecast = None

        # Fetch hourly forecast data
        if forecast_urls.get("hourly"):
            hourly_forecast = self.api_client.get_forecast_data(forecast_urls["hourly"])
            if not hourly_forecast:
                raise ApiError(f"Failed to fetch hourly forecast data from {forecast_urls['hourly']}.")

        # Fetch daily forecast data
        if forecast_urls.get("daily"):
            daily_forecast = self.api_client.get_forecast_data(forecast_urls["daily"])
            if not daily_forecast:
                raise ApiError(f"Failed to fetch daily forecast data from {forecast_urls['daily']}.")

        return {
            "coords": coords,
            "alerts": alerts,
            "hourly_forecast": hourly_forecast,
            "daily_forecast": daily_forecast
        }

    @Slot(object)
    def _on_location_data_loaded(self, result: Dict[str, Any]):
        """Handles the successful loading of all location data."""
        self.network_status_indicator.setText("● Network OK")
        self.network_status_indicator.setStyleSheet("color: green; font-weight: bold;")
        self.current_coords = result["coords"]
        alerts = result["alerts"] # Get alerts from the result

        self.log_to_gui(f"Successfully fetched data for {self.current_location_id} at {self.current_coords}",
                        level="INFO")
        self._update_alerts_display_area(alerts) # Update UI
        self._update_hourly_forecast_display(result["hourly_forecast"])
        self._update_daily_forecast_display(result["daily_forecast"])
        self.update_status(f"Data for {self.current_location_id} updated.")

        # Process the same alerts for speech if enabled
        if self.announce_alerts_action.isChecked():
            self._process_and_speak_alerts(alerts)

    @Slot(Exception)
    def _on_data_load_error(self, e: Exception):
        """Handles errors during background data fetching."""
        self.network_status_indicator.setText("● Network FAIL")
        self.network_status_indicator.setStyleSheet("color: red; font-weight: bold;")
        self.log_to_gui(str(e), level="ERROR")
        self.update_status(f"Error: {e}")
        self.current_coords = None
        self._update_alerts_display_area([])  # Clear alerts
        self._update_hourly_forecast_display(None)  # Clear forecasts
        self._update_daily_forecast_display(None)

    def _clear_and_set_loading_states(self):
        """Clears data displays and shows a 'Loading...' message."""
        self.alerts_display_area.clear()
        self.alerts_display_area.addItem("Loading alerts...")
        self._clear_layout(self.hourly_forecast_layout)
        self.hourly_forecast_layout.addWidget(QLabel("Loading..."), 0, 0)
        self._clear_layout(self.daily_forecast_layout)
        self.daily_forecast_layout.addWidget(QLabel("Loading..."), 0, 0)

    def _update_alerts_display_area(self, alerts: List[Any]):
        self.alerts_display_area.clear()
        if not alerts:
            self.alerts_display_area.addItem(f"No active alerts for {self.current_location_id}.")
            return

        for alert in alerts:
            title = alert.get('title', 'N/A Title')
            summary = alert.get('summary', 'No summary available.')
            item = QListWidgetItem(f"{title}\n\n{summary}")

            # Set color based on alert type
            title_lower = title.lower()
            if 'warning' in title_lower:
                item.setBackground(QColor("#ffdddd"))  # Light red
            elif 'watch' in title_lower:
                item.setBackground(QColor("#fff3cd"))  # Light orange
            elif 'advisory' in title_lower:
                item.setBackground(QColor("#d1ecf1"))  # Light blue
            self.alerts_display_area.addItem(item)

    def _update_hourly_forecast_display(self, forecast_json: Optional[Dict[str, Any]]):
        self._clear_layout(self.hourly_forecast_layout)
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            self.hourly_forecast_layout.addWidget(QLabel("8-Hour forecast data unavailable."), 0, 0)
            return

        periods = forecast_json['properties']['periods'][:8]
        headers = ["Time", "Temp", "Forecast"]
        for col, header in enumerate(headers):
            self.hourly_forecast_layout.addWidget(QLabel(f"<b>{header}</b>"), 0, col)

        for i, p in enumerate(periods):
            try:
                start_time_str = p.get('startTime', '')
                time_obj = time.strptime(start_time_str.split('T')[1].split('-')[0], "%H:%M:%S")
                formatted_time = time.strftime("%I %p", time_obj).lstrip('0')
                temp = f"{p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}"
                short_fc = p.get('shortForecast', 'N/A')

                self.hourly_forecast_layout.addWidget(QLabel(formatted_time), i + 1, 0)
                self.hourly_forecast_layout.addWidget(QLabel(temp), i + 1, 1)
                self.hourly_forecast_layout.addWidget(QLabel(short_fc), i + 1, 2)
            except Exception as e:
                self.log_to_gui(f"Error formatting hourly period: {e}", level="WARNING")

    def _update_daily_forecast_display(self, forecast_json: Optional[Dict[str, Any]]):
        self._clear_layout(self.daily_forecast_layout)
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            self.daily_forecast_layout.addWidget(QLabel("5-Day forecast data unavailable."), 0, 0)
            return

        periods = forecast_json['properties']['periods'][:10]
        headers = ["Period", "Temp", "Forecast"]
        for col, header in enumerate(headers):
            self.daily_forecast_layout.addWidget(QLabel(f"<b>{header}</b>"), 0, col)

        for i, p in enumerate(periods):
            try:
                name = p.get('name', 'N/A')
                temp = f"{p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}"
                short_fc = p.get('shortForecast', 'N/A')

                self.daily_forecast_layout.addWidget(QLabel(name), i + 1, 0)
                self.daily_forecast_layout.addWidget(QLabel(temp), i + 1, 1)
                self.daily_forecast_layout.addWidget(QLabel(short_fc), i + 1, 2)
            except Exception as e:
                self.log_to_gui(f"Error formatting daily period: {e}", level="WARNING")

    def _clear_layout(self, layout: QLayout):
        """Removes all widgets from a layout."""
        if layout is None: return
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _open_preferences_dialog(self):
        """Opens the comprehensive settings dialog."""
        # Gather all current settings to pass to the dialog
        current_prefs = {
            "repeater_info": self.current_repeater_info,
            "location_id": self.current_location_id,
            "interval_key": self.current_interval_key,
            "announce_alerts": self.announce_alerts_action.isChecked(),
            "auto_refresh_content": self.auto_refresh_action.isChecked(),
            "mute_audio": self.mute_action.isChecked(),
            "dark_mode_enabled": self.dark_mode_action.isChecked(),
            "show_log": self.show_log_action.isChecked(),
            "show_alerts_area": self.show_alerts_area_action.isChecked(),
            "show_forecasts_area": self.show_forecasts_area_action.isChecked(),
            "log_sort_order": self.current_log_sort_order,
        }

        dialog = SettingsDialog(self, current_settings=current_prefs)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_settings_data()

            # --- Apply General Settings ---
            location_changed = self.current_location_id != new_data["location_id"]
            interval_changed = self.current_interval_key != new_data["interval_key"]

            self.current_repeater_info = new_data["repeater_info"]
            self.current_location_id = new_data["location_id"]
            self.current_interval_key = new_data["interval_key"]

            # Update top bar widgets to reflect changes
            self.top_location_edit.setText(self.current_location_id)
            self.top_interval_combo.setCurrentText(self.current_interval_key)
            self._update_top_status_bar_display()

            if location_changed:
                self.log_to_gui(f"Location ID changed to: {self.current_location_id}", level="INFO")
                self.seen_alert_ids.clear()
                self._update_location_data()

            if interval_changed:
                self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
                    self.current_interval_key, FALLBACK_INITIAL_CHECK_INTERVAL_MS)
                self.log_to_gui(f"Interval changed to: {self.current_interval_key}", level="INFO")

            # --- Apply Behavior & Display Settings ---
            if self.announce_alerts_action.isChecked() != new_data["announce_alerts"]:
                self.announce_alerts_action.setChecked(new_data["announce_alerts"])

            if self.auto_refresh_action.isChecked() != new_data["auto_refresh_content"]:
                self.auto_refresh_action.setChecked(new_data["auto_refresh_content"])

            if self.mute_action.isChecked() != new_data["mute_audio"]:
                self.mute_action.setChecked(new_data["mute_audio"])

            if self.dark_mode_action.isChecked() != new_data["dark_mode_enabled"]:
                self.dark_mode_action.setChecked(new_data["dark_mode_enabled"])

            if self.show_log_action.isChecked() != new_data["show_log"]:
                self.show_log_action.setChecked(new_data["show_log"])

            if self.show_alerts_area_action.isChecked() != new_data["show_alerts_area"]:
                self.show_alerts_area_action.setChecked(new_data["show_alerts_area"])

            if self.show_forecasts_area_action.isChecked() != new_data["show_forecasts_area"]:
                self.show_forecasts_area_action.setChecked(new_data["show_forecasts_area"])

            if self.current_log_sort_order != new_data["log_sort_order"]:
                self.current_log_sort_order = new_data["log_sort_order"]
                self._apply_log_sort()

            self._update_main_timer_state()

            # --- Save all changes ---
            self._save_settings()
            self.log_to_gui("Preferences updated.", level="INFO")

    @Slot()
    def perform_check_cycle(self):
        """The main periodic task, now simplified to trigger background updates."""
        if not (self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()):
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            self.top_countdown_label.setText("Next Check: --:-- (Paused)")
            return

        self.main_check_timer.stop()

        if self.auto_refresh_action.isChecked() and QWebEngineView and self.web_view:
            # For auto-refresh, we'll just reload the current view.
            # Note: If the current view is a "Loading PDF..." message, this will reload that message.
            # The actual PDF opening is handled on source selection.
            self.web_view.reload()

        # Fetch ALL data in the background. The completion slot will handle speaking.
        self._update_location_data()

        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
        if self.current_check_interval_ms > 0:
            self.main_check_timer.start(self.current_check_interval_ms)

    @Slot(object)
    def _process_and_speak_alerts(self, alerts: List[Any]):
        """Processes alerts, flashes the window, and speaks new ones."""
        new_alerts_found = False
        high_priority_keywords = ["tornado", "severe thunderstorm", "flash flood warning"]

        for alert in alerts:
            if alert.id not in self.seen_alert_ids:
                new_alerts_found = True
                alert_title_lower = alert.title.lower()
                self.log_to_gui(f"New Alert: {alert.title}", level="IMPORTANT")

                # Check if this is a high-priority alert
                if any(keyword in alert_title_lower for keyword in high_priority_keywords):
                    self.log_to_gui("High-priority alert detected. Triggering extra notifications.", level="INFO")
                    QApplication.alert(self)  # Flash the application window/taskbar icon

                # Speak the alert (as before)
                self._speak_weather_alert(alert.title, alert.summary)
                self.seen_alert_ids.add(alert.id)

        if not new_alerts_found and alerts:
            self.log_to_gui(f"No new alerts. Total active: {len(alerts)}.", level="INFO")

        self._speak_repeater_info()

    def log_to_gui(self, message: str, level: str = "INFO"):
        """Logs a message to the standard logger and either the GUI or a buffer if the GUI is not ready."""
        formatted_message = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level.upper()}] {message}"
        if hasattr(self, 'log_area'):
            # In a sorted view, new messages are just appended. The user can re-sort manually.
            self.log_area.append(formatted_message)
        else:
            self._log_buffer.append(formatted_message)
        getattr(logging, level.lower(), logging.info)(message)

    def update_status(self, message: str):
        self.status_bar.showMessage(message, 5000)  # Show for 5 seconds

    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Quit Application', "Are you sure you want to quit?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log_to_gui("Shutting down...", level="INFO")
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            self.clock_timer.stop()
            self.thread_pool.waitForDone()  # Wait for background tasks to finish
            self._save_settings()
            event.accept()
        else:
            event.ignore()

    # --- TTS Engine ---
    class _DummyEngine:
        def say(self, text, name=None): logging.info(f"TTS (Dummy): {text}")

        def runAndWait(self): pass

        def stop(self): pass

        def isBusy(self): return False

    def _initialize_tts_engine(self):
        try:
            engine = pyttsx3.init()
            # A more robust way to check for a valid engine is to try to access a property.
            # If this fails, or there are no voices, the engine is not functional.
            voices = engine.getProperty('voices')
            if not voices:
                raise RuntimeError("No TTS voices found on the system.")
            return engine
        except Exception as e:
            self.log_to_gui(f"TTS engine initialization failed: {e}. Voice announcements will be disabled.",
                            level="ERROR")
            return self._DummyEngine()

    def _speak_weather_alert(self, alert_title: str, alert_summary: str):
        msg = f"Weather Alert: {alert_title}. {alert_summary}"
        self._speak_message_internal(msg)

    def _speak_repeater_info(self):
        if self.current_repeater_info:
            self._speak_message_internal(self.current_repeater_info)

    def _speak_message_internal(self, text: str):
        if self.mute_action.isChecked():
            self.log_to_gui(f"Audio muted. Would have spoken: {text}", level="DEBUG")
            return
        if self.is_tts_dummy:
            self.tts_engine.say(text)
            return
        try:
            if self.tts_engine.isBusy(): self.tts_engine.stop()
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except Exception as e:
            self.log_to_gui(f"TTS error: {e}", level="ERROR")

    # --- UI Update and State Management Methods ---
    def _update_current_time_display(self):
        if hasattr(self, 'current_time_label'):
            self.current_time_label.setText(f"Current Time: {time.strftime('%I:%M:%S %p')}")

    def _update_top_status_bar_display(self):
        # This method now updates the editable widgets
        if hasattr(self, 'top_repeater_label'):
            self.top_repeater_label.setText(f"Repeater: {self.current_repeater_info or 'N/A'}")

    def _apply_loaded_settings_to_ui(self):
        self.announce_alerts_action.setChecked(self.current_announce_alerts_checked)
        self.auto_refresh_action.setChecked(self.current_auto_refresh_content_checked)
        self.mute_action.setChecked(self.current_mute_audio_checked)
        self.dark_mode_action.setChecked(self.current_dark_mode_enabled)
        self.show_log_action.setChecked(self.current_show_log_checked)
        self.show_alerts_area_action.setChecked(self.current_show_alerts_area_checked)
        self.show_forecasts_area_action.setChecked(self.current_show_forecasts_area_checked)

        # --- Manually set panel visibility on startup ---
        self.splitter.widget(1).setVisible(self.current_show_log_checked)
        self.alerts_group.setVisible(self.current_show_alerts_area_checked)
        self.combined_forecast_widget.setVisible(self.current_show_forecasts_area_checked)

        # Set initial values for the new editable top bar widgets
        self.top_location_edit.setText(self.current_location_id)
        self.top_interval_combo.setCurrentText(self.current_interval_key)

        self._update_top_status_bar_display()
        self._update_web_sources_menu()
        self._apply_color_scheme()
        self._apply_log_sort() # Apply initial sort order

        # Initial load of the radar URL, now handles PDFs via direct Chromium rendering
        if QWebEngineView and self.web_view:
            self._load_web_view_url(self.current_radar_url)

        self.log_to_gui("Settings applied to UI.", level="INFO")

    def _update_main_timer_state(self):
        is_active = self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()
        if is_active:
            if not self.main_check_timer.isActive():
                self.log_to_gui("Timed checks starting.", level="INFO")
                QTimer.singleShot(100, self.perform_check_cycle)
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
        else:
            self.log_to_gui("Timed checks paused.", level="INFO")
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            self.top_countdown_label.setText("Next Check: --:-- (Paused)")

    def _reset_and_start_countdown(self, total_seconds: int):
        self.countdown_timer.stop()
        self.remaining_time_seconds = total_seconds
        if total_seconds > 0 and (self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()):
            self.countdown_timer.start(1000)
        self._update_countdown_display()

    def _update_countdown_display(self):
        if self.remaining_time_seconds > 0:
            self.remaining_time_seconds -= 1
        is_active = self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()
        if not is_active:
            self.top_countdown_label.setText("Next Check: --:-- (Paused)")
        else:
            minutes, seconds = divmod(self.remaining_time_seconds, 60)
            self.top_countdown_label.setText(f"Next Check: {minutes:02d}:{seconds:02d}")

    # --- Action Handlers ---
    def _on_announce_alerts_toggled(self, checked):
        self.current_announce_alerts_checked = checked
        self._update_main_timer_state()
        self._save_settings()

    def _on_auto_refresh_content_toggled(self, checked):
        self.current_auto_refresh_content_checked = checked
        self._update_main_timer_state()
        self._save_settings()

    def _on_mute_toggled(self, checked):
        self.current_mute_audio_checked = checked

        # Ensure both the action and the button reflect the state
        # (This might cause a recursive call if not careful, but PySide6 handles this
        # by not emitting 'toggled' if the state is already the target state)
        self.mute_action.setChecked(checked)
        self.mute_button.setChecked(checked)

        style = self.style()  # Get the current style to access standard icons
        if checked:
            # Muted state: show muted icon
            self.mute_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted))
            self.mute_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted))
        else:
            # Unmuted state: show unmuted icon
            self.mute_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
            self.mute_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume))

        self._save_settings()

    def _on_dark_mode_toggled(self, checked):
        self.current_dark_mode_enabled = checked
        self._apply_color_scheme()
        self._save_settings()

    def _on_show_log_toggled(self, checked):
        self.splitter.widget(1).setVisible(checked)
        self._save_settings()

    def _on_show_alerts_toggled(self, checked):
        self.alerts_group.setVisible(checked)
        self._save_settings()

    def _on_show_forecasts_toggled(self, checked):
        self.combined_forecast_widget.setVisible(checked)
        self._save_settings()

    def _on_speak_and_reset_button_press(self):
        if self.announce_alerts_action.isChecked():
            self._speak_repeater_info()
        self._update_main_timer_state()

    def _show_about_dialog(self):
        AboutDialog(self).exec()

    def _show_github_help(self):
        QDesktopServices.openUrl(QUrl(GITHUB_HELP_URL))

    # --- Top Bar Editable Field Handlers ---
    @Slot()
    def _on_top_location_apply_clicked(self):
        new_location_id = self.top_location_edit.text().strip().upper()
        if new_location_id and new_location_id != self.current_location_id:
            self.current_location_id = new_location_id
            self.log_to_gui(f"Location ID changed to: {self.current_location_id} (from top bar)", level="INFO")
            self.seen_alert_ids.clear()  # Clear seen alerts for new location
            self._update_location_data()  # Trigger data fetch for new location
            self._update_main_timer_state()  # Update timer state if needed
            self._save_settings()
        elif not new_location_id:
            self.log_to_gui("Location ID cannot be empty.", level="WARNING")
            self.top_location_edit.setText(self.current_location_id)  # Revert to last valid

    @Slot(str)
    def _on_top_interval_changed(self, new_interval_key: str):
        if new_interval_key and new_interval_key != self.current_interval_key:
            self.current_interval_key = new_interval_key
            self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
                self.current_interval_key, FALLBACK_INITIAL_CHECK_INTERVAL_MS)
            self.log_to_gui(f"Interval changed to: {self.current_interval_key} (from top bar)", level="INFO")
            self._update_main_timer_state()  # Update timer state
            self._save_settings()

    # --- Web Source Management ---
    def _update_web_sources_menu(self):
        self.web_sources_menu.clear()
        self.web_source_action_group = QActionGroup(self)
        self.web_source_action_group.setExclusive(True)
        style = self.style()

        for name, url in self.RADAR_OPTIONS.items():
            action = QAction(name, self, checkable=True)
            action.setData(url)
            action.triggered.connect(self._on_radar_source_selected)
            if url == self.current_radar_url:
                action.setChecked(True)
            self.web_sources_menu.addAction(action)
            self.web_source_action_group.addAction(action)

        self.web_sources_menu.addSeparator()

        open_in_browser_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DesktopIcon),
                                         "Open Current in Browser", self)
        open_in_browser_action.triggered.connect(self._open_current_in_browser)
        self.web_sources_menu.addAction(open_in_browser_action)

        save_current_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
                                      ADD_CURRENT_SOURCE_TEXT, self)
        save_current_action.triggered.connect(self._save_current_web_source)
        self.web_sources_menu.addAction(save_current_action)

        self.web_sources_menu.addSeparator()

        add_action = self.web_sources_menu.addAction(ADD_NEW_SOURCE_TEXT)
        add_action.triggered.connect(self._add_new_web_source)
        manage_action = self.web_sources_menu.addAction(MANAGE_SOURCES_TEXT)
        manage_action.triggered.connect(self._manage_web_sources)

    def _show_web_source_quick_select_menu(self):
        menu = QMenu(self)
        for name, url in self.RADAR_OPTIONS.items():
            action = menu.addAction(name)
            action.setData(url)

        chosen_action = menu.exec(
            self.web_source_quick_select_button.mapToGlobal(self.web_source_quick_select_button.rect().bottomLeft()))
        if chosen_action:
            self._on_radar_source_selected(True, action_to_use=chosen_action)

    def _on_radar_source_selected(self, checked, action_to_use=None):
        if not checked: return
        action = action_to_use or self.sender()
        if action:
            url_str = action.data()  # Get the URL string
            self.current_radar_url = url_str
            self._last_valid_radar_text = action.text()

            self._load_web_view_url(url_str)  # Use the new helper method

            self._save_settings()
            self._update_web_sources_menu()

    def _load_web_view_url(self, url_str: str):
        """Helper method to load any URL into QWebEngineView, handling PDFs by opening externally."""
        if QWebEngineView and self.web_view:
            if url_str.lower().endswith('.pdf'):
                # Display a message in the QWebEngineView
                self.web_view.setHtml(
                    f"<html><body><div style='text-align: center; margin-top: 50px; font-size: 18px; color: grey;'>Loading PDF...<br><br>Opening <a href='{url_str}'>{self._last_valid_radar_text}</a> in external viewer.</div></body></html>")
                self.log_to_gui(f"Opening PDF: {self._last_valid_radar_text} externally.", level="INFO")
                # Open the PDF URL in the default external viewer
                QDesktopServices.openUrl(QUrl(url_str))
            else:
                # Load non-PDF URLs directly
                self.web_view.setUrl(QUrl(url_str))
                self.log_to_gui(f"Loading web source: {self._last_valid_radar_text}", level="INFO")
        else:
            # Fallback for when QWebEngineView is not available
            self.log_to_gui(f"QWebEngineView not available. Opening {self._last_valid_radar_text} externally.",
                            level="WARNING")
            QDesktopServices.openUrl(QUrl(url_str))

    @Slot()
    def _open_current_in_browser(self):
        """Opens the current web view URL in the user's default browser."""
        if not QWebEngineView or not self.web_view:
            self.log_to_gui("Web view is not available.", level="WARNING")
            return

        current_url = self.web_view.url()
        if current_url.isValid() and not current_url.isEmpty():
            QDesktopServices.openUrl(current_url)
            self.log_to_gui(f"Opening {current_url.toString()} in external browser.", level="INFO")
        else:
            self.log_to_gui("No valid URL to open in browser.", level="WARNING")

    @Slot()
    def _save_current_web_source(self):
        """Saves the current URL in the web view as a new source."""
        if not QWebEngineView or not self.web_view:
            self.log_to_gui("Web view is not available.", level="WARNING")
            return

        current_url = self.web_view.url().toString()

        # Don't save empty or internal URLs
        if not current_url or current_url == "about:blank" or not current_url.startswith("http"):
            QMessageBox.warning(self, "Cannot Save Source", "The current page does not have a savable URL.")
            return

        # Open the dialog with the URL pre-filled
        dialog = AddEditSourceDialog(self, current_url=current_url)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if data:
                name, url = data
                if name in self.RADAR_OPTIONS:
                    QMessageBox.warning(self, "Duplicate Name", f"A source with the name '{name}' already exists.")
                    return

                # Add the new source
                self.RADAR_OPTIONS[name] = url
                self.log_to_gui(f"Saved new web source: '{name}' -> {url}", level="INFO")

                # Update the UI to reflect the new source as the current one
                self.current_radar_url = url
                self._last_valid_radar_text = name

                # Refresh menus and save
                self._update_web_sources_menu()
                self._save_settings()

    def _add_new_web_source(self):
        dialog = AddEditSourceDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if data:
                name, url = data
                if name in self.RADAR_OPTIONS:
                    QMessageBox.warning(self, "Duplicate Name", f"A source with the name '{name}' already exists.")
                    return
                self.RADAR_OPTIONS[name] = url
                self.current_radar_url = url
                self._update_web_sources_menu()
                self._on_radar_source_selected(True, action_to_use=self.web_source_action_group.actions()[-1])
                self._save_settings()

    def _manage_web_sources(self):
        dialog = ManageSourcesDialog(self.RADAR_OPTIONS, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.RADAR_OPTIONS = dialog.get_sources()
            if self.current_radar_url not in self.RADAR_OPTIONS.values():
                if self.RADAR_OPTIONS:
                    self.current_radar_url = list(self.RADAR_OPTIONS.values())[0]
                else:
                    self.current_radar_url = ""
            self._update_web_sources_menu()
            self._save_settings()

    def _get_display_name_for_url(self, url_to_find: str) -> Optional[str]:
        for name, url in self.RADAR_OPTIONS.items():
            if url == url_to_find:
                return name
        return None

    # --- Log Sorting ---
    def _sort_log(self, reverse: bool):
        """Sorts the log area's content."""
        if not hasattr(self, 'log_area'):
            return
        lines = self.log_area.toPlainText().splitlines()
        if not lines:
            return
        sorted_lines = sorted(lines, reverse=reverse)
        self.log_area.setPlainText("\n".join(sorted_lines))
        self.log_to_gui(f"Log sorted {'descending' if reverse else 'ascending'}.", level="DEBUG")

    @Slot()
    def _sort_log_ascending(self):
        self._sort_log(reverse=False)

    @Slot()
    def _sort_log_descending(self):
        self._sort_log(reverse=True)

    def _apply_log_sort(self):
        """Applies the stored log sort preference."""
        if self.current_log_sort_order == "ascending":
            self._sort_log(reverse=False)
        elif self.current_log_sort_order == "descending":
            self._sort_log(reverse=True)
        # If "chronological", do nothing.

    # --- Settings Backup/Restore and Theming ---
    def _backup_settings(self):
        src_path = self.settings_manager.file_path
        if not os.path.exists(src_path):
            QMessageBox.warning(self, "Backup Failed", "No settings file to back up.")
            return
        dest_path, _ = QFileDialog.getSaveFileName(self, "Backup Settings",
                                                   f"PyWeatherAlert_backup_{time.strftime('%Y%m%d')}.txt",
                                                   "Text Files (*.txt)")
        if dest_path:
            try:
                shutil.copy2(src_path, dest_path)
                self.update_status("Settings backed up successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Backup Error", f"Could not back up settings: {e}")

    def _restore_settings(self):
        src_path, _ = QFileDialog.getOpenFileName(self, "Restore Settings", "", "Text Files (*.txt)")
        if src_path:
            dest_path = self.settings_manager.file_path
            try:
                shutil.copy2(src_path, dest_path)
                QMessageBox.information(self, "Restore Complete",
                                        "Settings restored. The application will now restart to apply changes.")
                self.close()
                os.execl(sys.executable, sys.executable, *sys.argv)
            except Exception as e:
                QMessageBox.critical(self, "Restore Error", f"Could not restore settings: {e}")

    def _on_dark_mode_toggled(self, checked):
        self.current_dark_mode_enabled = checked
        self._apply_color_scheme()
        self._save_settings()

    def _apply_color_scheme(self):
        """Applies the appropriate stylesheet (light or dark)."""
        stylesheet_name = DARK_STYLESHEET_FILE_NAME if self.current_dark_mode_enabled else LIGHT_STYLESHEET_FILE_NAME
        stylesheet_path = os.path.join(self._get_resources_path(), stylesheet_name)

        # Create placeholder stylesheets if they don't exist
        if not os.path.exists(stylesheet_path):
            self._create_placeholder_stylesheet(stylesheet_path, self.current_dark_mode_enabled)

        try:
            with open(stylesheet_path, "r") as f:
                self.setStyleSheet(f.read())
            self.log_to_gui(f"Applied {stylesheet_name} theme.", level="INFO")
        except FileNotFoundError:
            self.log_to_gui(f"Stylesheet not found: {stylesheet_path}. Using default style.", level="WARNING")
            self.setStyleSheet("")  # Reset to default

    def _create_placeholder_stylesheet(self, path: str, is_dark: bool):
        """Creates a basic QSS file for modern light/dark themes."""
        if is_dark:
            content = """
            QWidget { background-color: #2b2b2b; color: #f0f0f0; }
            QGroupBox { border: 1px solid #444; margin-top: 1em; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }
            QTextEdit, QListWidget { background-color: #3c3c3c; border: 1px solid #555; }
            QPushButton { background-color: #555; border: 1px solid #666; padding: 5px; }
            QPushButton:hover { background-color: #666; }
            QPushButton:pressed { background-color: #777; }
            """
        else:
            content = """
            QWidget { background-color: #f0f0f0; color: #000; }
            QGroupBox { border: 1px solid #ccc; margin-top: 1em; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }
            QTextEdit, QListWidget { background-color: #fff; border: 1px solid #ccc; }
            QPushButton { background-color: #e0e0e0; border: 1px solid #ccc; padding: 5px; }
            QPushButton:hover { background-color: #e8e8e8; }
            QPushButton:pressed { background-color: #d0d0d0; }
            """
        try:
            with open(path, "w") as f:
                f.write(content)
            self.log_to_gui(f"Created placeholder stylesheet at {path}", level="INFO")
        except IOError as e:
            self.log_to_gui(f"Could not create placeholder stylesheet: {e}", level="ERROR")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if "Fusion" in QStyleFactory.keys():
        app.setStyle(QStyleFactory.create("Fusion"))

    main_win = WeatherAlertApp()
    main_win.show()
    sys.exit(app.exec())