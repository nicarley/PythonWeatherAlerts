
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
import pickle
from collections import deque

# PySide6 imports
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QMessageBox,
    QStatusBar, QCheckBox, QSplitter, QStyleFactory, QGroupBox, QDialog,
    QDialogButtonBox, QFormLayout, QListWidget, QListWidgetItem, QLayout,
    QSpacerItem, QSizePolicy, QFileDialog, QFrame, QMenu, QStyle, QTableWidget,
    QTableWidgetItem, QHeaderView, QSystemTrayIcon, QTabWidget
)
from PySide6.QtCore import Qt, QTimer, Slot, QUrl, QFile, QTextStream, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import (
    QTextCursor, QIcon, QColor, QDesktopServices, QPalette, QAction,
    QActionGroup, QFont, QPixmap
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None
    logging.warning("PySide6.QtWebEngineWidgets not found. Web view will be disabled.")

# --- Application Version ---
versionnumber = "25.08.07"

# --- Constants ---
FALLBACK_INITIAL_CHECK_INTERVAL_MS = 900 * 1000
FALLBACK_DEFAULT_INTERVAL_KEY = "15 Minutes"
FALLBACK_DEFAULT_LOCATIONS = [{"name": "Default", "id": "62881"}]
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
FALLBACK_ENABLE_SOUNDS = True
FALLBACK_ENABLE_DESKTOP_NOTIFICATIONS = True

CHECK_INTERVAL_OPTIONS = {
    "1 Minute": 1 * 60 * 1000, "5 Minutes": 5 * 60 * 1000,
    "10 Minutes": 10 * 60 * 1000, "15 Minutes": 15 * 60 * 1000,
    "30 Minutes": 30 * 60 * 1000, "1 Hour": 60 * 60 * 1000,
}

NWS_STATION_API_URL_TEMPLATE = "https://api.weather.gov/stations/{station_id}"
NWS_POINTS_API_URL_TEMPLATE = "https://api.weather.gov/points/{latitude},{longitude}"
WEATHER_URL_PREFIX = "https://api.weather.gov/alerts/active.atom?point="
WEATHER_URL_SUFFIX = "&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Immediate%2CFuture%2CExpected"

SETTINGS_FILE_NAME = "settings.txt"
RESOURCES_FOLDER_NAME = "resources"
ICONS_FOLDER_NAME = "icons"
LIGHT_STYLESHEET_FILE_NAME = "modern.qss"
DARK_STYLESHEET_FILE_NAME = "dark_modern.qss"
ALERT_HISTORY_FILE = "alert_history.dat"

ADD_NEW_SOURCE_TEXT = "Add New Source..."
MANAGE_SOURCES_TEXT = "Manage Sources..."
ADD_CURRENT_SOURCE_TEXT = "Add Current View as Source..."

MAX_HISTORY_ITEMS = 100

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
class AlertHistoryManager:
    """Manages persistent storage of seen alerts."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.seen_alerts = set()
        self.alert_history = deque(maxlen=MAX_HISTORY_ITEMS)
        self._load_history()

    def _load_history(self):
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'rb') as f:
                    data = pickle.load(f)
                    self.seen_alerts = data.get('seen_alerts', set())
                    self.alert_history = data.get('history', deque(maxlen=MAX_HISTORY_ITEMS))
        except Exception as e:
            logging.error(f"Error loading alert history: {e}")

    def save_history(self):
        try:
            with open(self.file_path, 'wb') as f:
                pickle.dump({
                    'seen_alerts': self.seen_alerts,
                    'history': self.alert_history
                }, f)
        except Exception as e:
            logging.error(f"Error saving alert history: {e}")

    def add_alert(self, alert_id: str, alert_data: dict):
        if alert_id not in self.seen_alerts:
            self.seen_alerts.add(alert_id)
            self.alert_history.appendleft(alert_data)
            return True
        return False

    def get_recent_alerts(self, count=5) -> list:
        return list(self.alert_history)[:count]


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


class AddEditLocationDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, current_name: Optional[str] = None,
                 current_id: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Location" if current_name else "Add New Location")
        self.layout = QFormLayout(self)
        self.name_edit = QLineEdit(self)
        self.id_edit = QLineEdit(self)
        self.id_edit.setPlaceholderText("e.g., 62881 or KSTL")
        if current_name: self.name_edit.setText(current_name)
        if current_id: self.id_edit.setText(current_id)
        self.layout.addRow("Location Name:", self.name_edit)
        self.layout.addRow("Zip/Airport ID:", self.id_edit)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        Qt.Orientation.Horizontal, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_data(self) -> Optional[Tuple[str, str]]:
        name = self.name_edit.text().strip()
        location_id = self.id_edit.text().strip().upper()
        if name and location_id:
            return name, location_id
        QMessageBox.warning(self, "Invalid Input", "Please provide a valid name and location ID.")
        return None


class ManageLocationsDialog(QDialog):
    def __init__(self, locations: List[Dict[str, str]], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Manage Locations")
        self.locations: List[Dict[str, str]] = locations
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        for loc in self.locations:
            self.list_widget.addItem(f"{loc['name']} ({loc['id']})")
        layout.addWidget(self.list_widget)

        button_layout = QHBoxLayout()
        add_button = QPushButton("Add...")
        add_button.clicked.connect(self.add_location)
        edit_button = QPushButton("Edit...")
        edit_button.clicked.connect(self.edit_location)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self.remove_location)

        button_layout.addWidget(add_button)
        button_layout.addWidget(edit_button)
        button_layout.addWidget(remove_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)

    def add_location(self):
        dialog = AddEditLocationDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data: return
            name, loc_id = data
            if any(loc['name'] == name for loc in self.locations):
                QMessageBox.warning(self, "Duplicate Name", f"A location with the name '{name}' already exists.")
                return
            self.locations.append({"name": name, "id": loc_id})
            self.list_widget.addItem(f"{name} ({loc_id})")

    def edit_location(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item:
            return
        current_row = self.list_widget.currentRow()
        old_loc = self.locations[current_row]

        dialog = AddEditLocationDialog(self, current_name=old_loc['name'], current_id=old_loc['id'])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data: return
            new_name, new_id = data

            if new_name != old_loc['name'] and any(
                    loc['name'] == new_name for i, loc in enumerate(self.locations) if i != current_row):
                QMessageBox.warning(self, "Duplicate Name", f"A location with the name '{new_name}' already exists.")
                return

            self.locations[current_row] = {"name": new_name, "id": new_id}
            selected_item.setText(f"{new_name} ({new_id})")

    def remove_location(self):
        current_row = self.list_widget.currentRow()
        if current_row == -1:
            return

        if len(self.locations) <= 1:
            QMessageBox.warning(self, "Cannot Remove", "You must have at least one location.")
            return

        loc_to_remove = self.locations[current_row]
        reply = QMessageBox.question(self, "Confirm Removal", f"Are you sure you want to remove '{loc_to_remove['name']}'?")
        if reply == QMessageBox.StandardButton.Yes:
            self.locations.pop(current_row)
            self.list_widget.takeItem(current_row)

    def get_locations(self) -> List[Dict[str, str]]:
        return self.locations


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
        self.sources_list: List[Tuple[str, str]] = list(sources.items())
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
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
        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(self.move_up_source)
        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(self.move_down_source)

        button_layout.addWidget(add_button)
        button_layout.addWidget(edit_button)
        button_layout.addWidget(remove_button)
        button_layout.addStretch()
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
            if any(n == name for n, _ in self.sources_list):
                QMessageBox.warning(self, "Duplicate Name", f"A source with the name '{name}' already exists.")
                return
            self.sources_list.append((name, url))
            self.list_widget.addItem(name)
            self.list_widget.setCurrentRow(len(self.sources_list) - 1)

    def edit_source(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item:
            return
        current_row = self.list_widget.currentRow()
        old_name, old_url = self.sources_list[current_row]

        dialog = AddEditSourceDialog(self, current_name=old_name, current_url=old_url)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data: return
            new_name, new_url = data

            if new_name != old_name and any(
                    n == new_name for i, (n, _) in enumerate(self.sources_list) if i != current_row):
                QMessageBox.warning(self, "Duplicate Name", f"A source with the name '{new_name}' already exists.")
                return

            self.sources_list[current_row] = (new_name, new_url)
            selected_item.setText(new_name)

    def remove_source(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item:
            return
        current_row = self.list_widget.currentRow()
        name_to_remove = self.sources_list[current_row][0]

        reply = QMessageBox.question(self, "Confirm Removal", f"Are you sure you want to remove '{name_to_remove}'?")
        if reply == QMessageBox.StandardButton.Yes:
            self.sources_list.pop(current_row)
            self.list_widget.takeItem(current_row)

    def move_up_source(self):
        current_row = self.list_widget.currentRow()
        if current_row > 0:
            item_to_move = self.sources_list.pop(current_row)
            self.sources_list.insert(current_row - 1, item_to_move)
            q_item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row - 1, q_item)
            self.list_widget.setCurrentRow(current_row - 1)

    def move_down_source(self):
        current_row = self.list_widget.currentRow()
        if current_row < len(self.sources_list) - 1:
            item_to_move = self.sources_list.pop(current_row)
            self.sources_list.insert(current_row + 1, item_to_move)
            q_item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row + 1, q_item)
            self.list_widget.setCurrentRow(current_row + 1)

    def get_sources(self) -> Dict[str, str]:
        return dict(self.sources_list)


class AlertHistoryDialog(QDialog):
    def __init__(self, history_data: List[dict], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Alert History")
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout()
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Time", "Type", "Location", "Summary"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for alert in history_data:
            self._add_alert_to_table(alert)

        clear_button = QPushButton("Clear History")
        clear_button.clicked.connect(self._clear_history)

        layout.addWidget(self.table)
        layout.addWidget(clear_button)
        self.setLayout(layout)

    def _add_alert_to_table(self, alert: dict):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(alert.get('time', '')))
        self.table.setItem(row, 1, QTableWidgetItem(alert.get('type', '')))
        self.table.setItem(row, 2, QTableWidgetItem(alert.get('location', '')))
        self.table.setItem(row, 3, QTableWidgetItem(alert.get('summary', '')))

    def _clear_history(self):
        self.table.setRowCount(0)


class SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, current_settings: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.current_settings = current_settings if current_settings else {}

        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # --- General Settings ---
        general_tab = QWidget()
        form_layout = QFormLayout(general_tab)

        self.repeater_entry = QLineEdit(self.current_settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO))
        form_layout.addRow("Repeater Announcement:", self.repeater_entry)

        self.interval_combobox = QComboBox()
        self.interval_combobox.addItems(CHECK_INTERVAL_OPTIONS.keys())
        self.interval_combobox.setCurrentText(self.current_settings.get("interval_key", FALLBACK_DEFAULT_INTERVAL_KEY))
        form_layout.addRow("Check Interval:", self.interval_combobox)

        self.tabs.addTab(general_tab, "General")

        # --- Locations Tab ---
        locations_tab = QWidget()
        locations_layout = QVBoxLayout(locations_tab)
        self.manage_locations_button = QPushButton("Manage Locations...")
        self.manage_locations_button.clicked.connect(self._open_manage_locations_dialog)
        locations_layout.addWidget(self.manage_locations_button)
        locations_layout.addStretch()
        self.tabs.addTab(locations_tab, "Locations")

        # --- Behavior & Display Settings ---
        behavior_tab = QWidget()
        behavior_form_layout = QFormLayout(behavior_tab)

        self.announce_alerts_check = QCheckBox("Announce Alerts and Start Timer")
        self.announce_alerts_check.setChecked(
            self.current_settings.get("announce_alerts", FALLBACK_ANNOUNCE_ALERTS_CHECKED))
        behavior_form_layout.addRow(self.announce_alerts_check)

        self.auto_refresh_check = QCheckBox("Auto-Refresh Web Content")
        self.auto_refresh_check.setChecked(
            self.current_settings.get("auto_refresh_content", FALLBACK_AUTO_REFRESH_CONTENT_CHECKED))
        behavior_form_layout.addRow(self.auto_refresh_check)

        self.mute_audio_check = QCheckBox("Mute All Audio")
        self.mute_audio_check.setChecked(self.current_settings.get("mute_audio", FALLBACK_MUTE_AUDIO_CHECKED))
        behavior_form_layout.addRow(self.mute_audio_check)

        self.notification_sound_check = QCheckBox("Enable Alert Sounds")
        self.notification_sound_check.setChecked(self.current_settings.get("enable_sounds", FALLBACK_ENABLE_SOUNDS))
        behavior_form_layout.addRow(self.notification_sound_check)
        
        self.desktop_notification_check = QCheckBox("Enable Desktop Notifications")
        self.desktop_notification_check.setChecked(self.current_settings.get("enable_desktop_notifications", FALLBACK_ENABLE_DESKTOP_NOTIFICATIONS))
        behavior_form_layout.addRow(self.desktop_notification_check)

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
        self.show_alerts_check.setChecked(
            self.current_settings.get("show_alerts_area", FALLBACK_SHOW_ALERTS_AREA_CHECKED))
        behavior_form_layout.addRow(self.show_alerts_check)

        self.show_forecasts_check = QCheckBox("Show Weather Forecast Area on Startup")
        self.show_forecasts_check.setToolTip("Show or hide the Weather Forecast panel.")
        self.show_forecasts_check.setChecked(
            self.current_settings.get("show_forecasts_area", FALLBACK_SHOW_FORECASTS_AREA_CHECKED))
        behavior_form_layout.addRow(self.show_forecasts_check)

        behavior_form_layout.addRow(QFrame(frameShape=QFrame.Shape.HLine, frameShadow=QFrame.Shadow.Sunken))

        self.log_sort_combo = QComboBox()
        self.log_sort_combo.addItems(["Chronological", "Ascending", "Descending"])
        self.log_sort_combo.setCurrentText(
            self.current_settings.get("log_sort_order", FALLBACK_LOG_SORT_ORDER).capitalize())
        behavior_form_layout.addRow("Initial Log Sort Order:", self.log_sort_combo)
        self.tabs.addTab(behavior_tab, "Behavior & Display")

        main_layout.addWidget(self.tabs)

        # --- Dialog Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def _open_manage_locations_dialog(self):
        dialog = ManageLocationsDialog(self.current_settings.get("locations", FALLBACK_DEFAULT_LOCATIONS), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current_settings["locations"] = dialog.get_locations()

    def get_settings_data(self) -> Dict[str, Any]:
        return {
            "repeater_info": self.repeater_entry.text(),
            "locations": self.current_settings.get("locations", FALLBACK_DEFAULT_LOCATIONS),
            "interval_key": self.interval_combobox.currentText(),
            "announce_alerts": self.announce_alerts_check.isChecked(),
            "auto_refresh_content": self.auto_refresh_check.isChecked(),
            "mute_audio": self.mute_audio_check.isChecked(),
            "enable_sounds": self.notification_sound_check.isChecked(),
            "enable_desktop_notifications": self.desktop_notification_check.isChecked(),
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
        self.alert_history_manager = AlertHistoryManager(
            os.path.join(self._get_resources_path(), ALERT_HISTORY_FILE))
        self.thread_pool = QThreadPool()
        self.log_to_gui(f"Multithreading with up to {self.thread_pool.maxThreadCount()} threads.", level="DEBUG")

        self.current_coords: Optional[Tuple[float, float]] = None

        # Initialize application state variables
        self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()
        self._last_valid_radar_text = FALLBACK_DEFAULT_RADAR_DISPLAY_NAME
        self.current_radar_url = FALLBACK_DEFAULT_RADAR_URL
        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.locations = FALLBACK_DEFAULT_LOCATIONS
        self.current_location_id = self.locations[0]["id"]
        self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
        self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
        self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED
        self.current_show_alerts_area_checked = FALLBACK_SHOW_ALERTS_AREA_CHECKED
        self.current_show_forecasts_area_checked = FALLBACK_SHOW_FORECASTS_AREA_CHECKED
        self.current_auto_refresh_content_checked = FALLBACK_AUTO_REFRESH_CONTENT_CHECKED
        self.current_dark_mode_enabled = FALLBACK_DARK_MODE_ENABLED
        self.current_log_sort_order = FALLBACK_LOG_SORT_ORDER
        self.current_mute_audio_checked = FALLBACK_MUTE_AUDIO_CHECKED
        self.current_enable_sounds = FALLBACK_ENABLE_SOUNDS
        self.current_enable_desktop_notifications = FALLBACK_ENABLE_DESKTOP_NOTIFICATIONS

        self._load_settings()
        self._set_window_icon()

        self.tts_engine = self._initialize_tts_engine()
        self.is_tts_dummy = isinstance(self.tts_engine, self._DummyEngine)

        self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
            self.current_interval_key, FALLBACK_INITIAL_CHECK_INTERVAL_MS)

        self.main_check_timer = QTimer(self)
        self.main_check_timer.timeout.connect(self.perform_check_cycle)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_countdown_display)
        self.remaining_time_seconds = 0
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_current_time_display)

        self._init_ui()
        self._apply_loaded_settings_to_ui()

        self.log_to_gui(f"Monitoring Location: {self.get_current_location_name()}", level="INFO")
        self._update_location_data(self.current_location_id)
        self._update_main_timer_state()

        # Start the clock timer
        self.clock_timer.start(1000)
        self._update_current_time_display()

    def get_current_location_name(self):
        for loc in self.locations:
            if loc["id"] == self.current_location_id:
                return loc["name"]
        return "Unknown"

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
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
            self.log_to_gui("Custom application icon not found. Using default PySide6 icon.", level="WARNING")

        self.setWindowIcon(icon)

    def _get_resources_path(self) -> str:
        base_path = os.path.dirname(os.path.abspath(__file__))
        resources_path = os.path.join(base_path, RESOURCES_FOLDER_NAME)
        os.makedirs(resources_path, exist_ok=True)
        icons_path = os.path.join(resources_path, ICONS_FOLDER_NAME)
        os.makedirs(icons_path, exist_ok=True)
        return resources_path

    def _load_settings(self):
        settings = self.settings_manager.load()
        if not settings:
            self._apply_fallback_settings("Settings file not found or invalid. Using defaults.")
            return

        self.current_repeater_info = settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO)
        self.locations = settings.get("locations", FALLBACK_DEFAULT_LOCATIONS)
        self.current_location_id = self.locations[0]["id"]
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
        self.current_enable_sounds = settings.get("enable_sounds", FALLBACK_ENABLE_SOUNDS)
        self.current_enable_desktop_notifications = settings.get("enable_desktop_notifications", FALLBACK_ENABLE_DESKTOP_NOTIFICATIONS)

        self._last_valid_radar_text = self._get_display_name_for_url(self.current_radar_url) or \
                                      (list(self.RADAR_OPTIONS.keys())[0] if self.RADAR_OPTIONS else "")

    def _apply_fallback_settings(self, reason_message: str):
        self.log_to_gui(reason_message, level="WARNING")
        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.locations = FALLBACK_DEFAULT_LOCATIONS
        self.current_location_id = self.locations[0]["id"]
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
        self.current_enable_sounds = FALLBACK_ENABLE_SOUNDS
        self.current_enable_desktop_notifications = FALLBACK_ENABLE_DESKTOP_NOTIFICATIONS

    @Slot()
    def _save_settings(self):
        settings = {
            "repeater_info": self.current_repeater_info,
            "locations": self.locations,
            "check_interval_key": self.current_interval_key,
            "radar_options_dict": self.RADAR_OPTIONS,
            "radar_url": self.current_radar_url,
            "announce_alerts": self.announce_alerts_action.isChecked(),
            "auto_refresh_content": self.auto_refresh_action.isChecked(),
            "mute_audio": self.mute_action.isChecked(),
            "enable_sounds": self.enable_sounds_action.isChecked(),
            "enable_desktop_notifications": self.desktop_notification_action.isChecked(),
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
        self.alerts_forecasts_container = QWidget()
        alerts_forecasts_layout = QHBoxLayout(self.alerts_forecasts_container)
        alerts_forecasts_layout.setContentsMargins(0,0,0,0)

        # Alerts Group
        self.alerts_group = QGroupBox("Current Alerts")
        alerts_layout = QVBoxLayout(self.alerts_group)

        # Add filter buttons
        filter_layout = QHBoxLayout()
        self.all_alerts_button = QPushButton("All", checkable=True, checked=True)
        self.warning_button = QPushButton("Warnings", checkable=True)
        self.watch_button = QPushButton("Watches", checkable=True)
        self.advisory_button = QPushButton("Advisories", checkable=True)

        for btn in [self.all_alerts_button, self.warning_button,
                    self.watch_button, self.advisory_button]:
            btn.clicked.connect(self._filter_alerts)
            filter_layout.addWidget(btn)

        alerts_layout.addLayout(filter_layout)

        self.alerts_display_area = QListWidget()
        self.alerts_display_area.setObjectName("AlertsDisplayArea")
        self.alerts_display_area.setWordWrap(True)
        self.alerts_display_area.setAlternatingRowColors(True)
        alerts_layout.addWidget(self.alerts_display_area)
        alerts_forecasts_layout.addWidget(self.alerts_group, 1)

        # Combined Forecasts Group
        self.combined_forecast_widget = QGroupBox("Weather Forecast")
        combined_forecast_main_layout = QHBoxLayout(self.combined_forecast_widget)
        combined_forecast_main_layout.setContentsMargins(5, 5, 5, 5)

        # Hourly Forecast Sub-Group
        hourly_forecast_sub_group = QGroupBox("8-Hour Forecast")
        hourly_forecast_sub_group_layout = QVBoxLayout(hourly_forecast_sub_group)
        hourly_forecast_sub_group_layout.setContentsMargins(5, 5, 5, 5)
        self.hourly_forecast_widget = QWidget()
        self.hourly_forecast_layout = QGridLayout(self.hourly_forecast_widget)
        self.hourly_forecast_layout.setContentsMargins(5, 5, 5, 5)
        self.hourly_forecast_layout.setSpacing(5)

        hourly_font = QFont()
        hourly_font.setPointSize(9)
        self.hourly_forecast_widget.setFont(hourly_font)

        hourly_forecast_sub_group_layout.addWidget(self.hourly_forecast_widget)
        combined_forecast_main_layout.addWidget(hourly_forecast_sub_group, 1)

        # Daily Forecast Sub-Group
        daily_forecast_sub_group = QGroupBox("5-Day Forecast")
        daily_forecast_sub_group_layout = QVBoxLayout(daily_forecast_sub_group)
        daily_forecast_sub_group_layout.setContentsMargins(5, 5, 5, 5)
        self.daily_forecast_widget = QWidget()
        self.daily_forecast_layout = QGridLayout(self.daily_forecast_widget)
        self.daily_forecast_layout.setContentsMargins(5, 5, 5, 5)
        self.daily_forecast_layout.setSpacing(5)

        daily_font = QFont()
        daily_font.setPointSize(9)
        self.daily_forecast_widget.setFont(daily_font)

        daily_forecast_sub_group_layout.addWidget(self.daily_forecast_widget)
        combined_forecast_main_layout.addWidget(daily_forecast_sub_group, 1)

        alerts_forecasts_layout.addWidget(self.combined_forecast_widget, 2)
        
        # --- Splitter for Main Content and Web View/Log ---
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.addWidget(self.alerts_forecasts_container)

        if QWebEngineView:
            self.web_view = QWebEngineView()
        else:
            self.web_view = QLabel("WebEngineView not available. Please install 'PySide6-WebEngine'.")
            self.web_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.log_and_web_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.log_and_web_splitter.addWidget(self.web_view)

        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_toolbar = QHBoxLayout()
        log_toolbar.addWidget(QLabel("<b>Application Log</b>"))
        log_toolbar.addStretch()

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
        self.log_and_web_splitter.addWidget(log_widget)

        if self._log_buffer:
            self.log_area.append("\n".join(self._log_buffer))
            self._log_buffer.clear()

        self.log_and_web_splitter.setSizes([600, 350])
        self.main_splitter.addWidget(self.log_and_web_splitter)
        self.main_splitter.setSizes([250, 600])

        main_layout.addWidget(self.main_splitter)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.network_status_indicator = QLabel("● Network OK")
        self.network_status_indicator.setStyleSheet("color: green; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.network_status_indicator)

        # Initialize system tray
        self._init_system_tray()

    def _init_system_tray(self):
        """Initializes the system tray icon and menu."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.windowIcon())

        tray_menu = QMenu()
        restore_action = tray_menu.addAction("Restore")
        restore_action.triggered.connect(self.showNormal)
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        """Handles tray icon activation (click/double-click)."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.showNormal()
            self.activateWindow()

    def _create_top_status_bar(self) -> QHBoxLayout:
        top_status_layout = QHBoxLayout()
        top_status_layout.setContentsMargins(5, 3, 5, 3)

        style = self.style()
        self.top_repeater_label = QLabel("Repeater: N/A")
        self.top_countdown_label = QLabel("Next Check: --:--")
        self.current_time_label = QLabel("Current Time: --:--:--")

        volume_icon_label = QLabel()
        volume_icon_label.setPixmap(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume).pixmap(16, 16))
        top_status_layout.addWidget(volume_icon_label)
        top_status_layout.addWidget(self.top_repeater_label)
        top_status_layout.addSpacing(20)

        location_icon_label = QLabel()
        location_icon_label.setPixmap(style.standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon).pixmap(16, 16))
        top_status_layout.addWidget(location_icon_label)

        self.location_combo = QComboBox()
        self.location_combo.setToolTip("Select a location to view")
        self.location_combo.currentIndexChanged.connect(self._on_location_selected)
        top_status_layout.addWidget(self.location_combo)

        top_status_layout.addSpacing(20)

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

        self.mute_button = QPushButton("Mute")
        self.mute_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted))
        self.mute_button.setToolTip("Mute All Audio")
        self.mute_button.setCheckable(True)
        self.mute_button.toggled.connect(self._on_mute_toggled)
        top_status_layout.addWidget(self.mute_button)

        top_status_layout.addStretch(1)
        top_status_layout.addWidget(self.top_countdown_label)
        top_status_layout.addSpacing(15)
        top_status_layout.addWidget(self.current_time_label)

        return top_status_layout

    def _create_menu_bar(self):
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

        # History Menu
        history_menu = menu_bar.addMenu("&History")
        view_history_action = QAction("View Alert History", self)
        view_history_action.triggered.connect(self._show_alert_history)
        history_menu.addAction(view_history_action)

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
        self.enable_sounds_action = QAction("Enable Alert Sounds", self, checkable=True)
        self.enable_sounds_action.toggled.connect(self._on_enable_sounds_toggled)
        actions_menu.addAction(self.enable_sounds_action)
        self.desktop_notification_action = QAction("Enable Desktop Notifications", self, checkable=True)
        self.desktop_notification_action.toggled.connect(self._on_desktop_notification_toggled)
        actions_menu.addAction(self.desktop_notification_action)
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

    def _update_location_data(self, location_id):
        self.update_status(f"Fetching data for {self.get_location_name_by_id(location_id)}...")
        self._clear_and_set_loading_states()

        worker = Worker(self._fetch_all_data_for_location, location_id)
        worker.signals.result.connect(self._on_location_data_loaded)
        worker.signals.error.connect(self._on_data_load_error)
        self.thread_pool.start(worker)

    def get_location_name_by_id(self, location_id):
        for loc in self.locations:
            if loc["id"] == location_id:
                return loc["name"]
        return "Unknown"

    def _fetch_all_data_for_location(self, location_id: str) -> Dict[str, Any]:
        coords = self.api_client.get_coordinates_for_location(location_id)
        if not coords:
            raise ValueError(f"Could not find coordinates for location '{location_id}'.")

        lat, lon = coords
        alerts = self.api_client.get_alerts(lat, lon)
        forecast_urls = self.api_client.get_forecast_urls(lat, lon)
        if not forecast_urls:
            raise ApiError(f"Could not retrieve forecast URLs for {lat},{lon}. API might be down or rate-limited.")

        hourly_forecast = None
        daily_forecast = None

        if forecast_urls.get("hourly"):
            hourly_forecast = self.api_client.get_forecast_data(forecast_urls["hourly"])
            if not hourly_forecast:
                raise ApiError(f"Failed to fetch hourly forecast data from {forecast_urls['hourly']}.")

        if forecast_urls.get("daily"):
            daily_forecast = self.api_client.get_forecast_data(forecast_urls["daily"])
            if not daily_forecast:
                raise ApiError(f"Failed to fetch daily forecast data from {forecast_urls['daily']}.")

        return {
            "location_id": location_id,
            "coords": coords,
            "alerts": alerts,
            "hourly_forecast": hourly_forecast,
            "daily_forecast": daily_forecast
        }

    @Slot(object)
    def _on_location_data_loaded(self, result: Dict[str, Any]):
        self.network_status_indicator.setText("● Network OK")
        self.network_status_indicator.setStyleSheet("color: green; font-weight: bold;")
        self.current_coords = result["coords"]
        alerts = result["alerts"]
        location_id = result["location_id"]

        self.log_to_gui(f"Successfully fetched data for {self.get_location_name_by_id(location_id)} at {self.current_coords}",
                        level="INFO")
        self._update_alerts_display_area(alerts, location_id)
        self._update_hourly_forecast_display(result["hourly_forecast"])
        self._update_daily_forecast_display(result["daily_forecast"])
        self.update_status(f"Data for {self.get_location_name_by_id(location_id)} updated.")

        if self.announce_alerts_action.isChecked():
            self._process_and_speak_alerts(alerts, location_id)

    @Slot(Exception)
    def _on_data_load_error(self, e: Exception):
        self.network_status_indicator.setText("● Network FAIL")
        self.network_status_indicator.setStyleSheet("color: red; font-weight: bold;")
        self.log_to_gui(str(e), level="ERROR")
        self.update_status(f"Error: {e}")
        self.current_coords = None
        self._update_alerts_display_area([], self.current_location_id)
        self._update_hourly_forecast_display(None)
        self._update_daily_forecast_display(None)

    def _clear_and_set_loading_states(self):
        self.alerts_display_area.clear()
        self.alerts_display_area.addItem("Loading alerts...")
        self._clear_layout(self.hourly_forecast_layout)
        self.hourly_forecast_layout.addWidget(QLabel("Loading..."), 0, 0)
        self._clear_layout(self.daily_forecast_layout)
        self.daily_forecast_layout.addWidget(QLabel("Loading..."), 0, 0)

    def _update_alerts_display_area(self, alerts: List[Any], location_id: str):
        self.alerts_display_area.clear()
        if not alerts:
            self.alerts_display_area.addItem(f"No active alerts for {self.get_location_name_by_id(location_id)}.")
            return

        for alert in alerts:
            title = alert.get('title', 'N/A Title')
            summary = alert.get('summary', 'No summary available.')
            item = QListWidgetItem(f"{title}\n\n{summary}")

            # Track in history
            is_new = self.alert_history_manager.add_alert(
                alert.id,
                {
                    'time': time.strftime('%Y-%m-%d %H:%M'),
                    'type': title.split(' ')[0],
                    'location': self.get_location_name_by_id(location_id),
                    'summary': summary
                }
            )

            # Highlight new alerts
            if is_new:
                item.setBackground(QColor("#ffcccc"))  # Light red for new alerts
                self._play_alert_sound(title.lower())
                if self.desktop_notification_action.isChecked():
                    self._show_desktop_notification(f"{self.get_location_name_by_id(location_id)}: {title}", summary)

            # Color coding by alert type
            title_lower = title.lower()
            if 'warning' in title_lower:
                item.setForeground(QColor("#cc0000"))  # Red text
            elif 'watch' in title_lower:
                item.setForeground(QColor("#ff9900"))  # Orange text
            elif 'advisory' in title_lower:
                item.setForeground(QColor("#0066cc"))  # Blue text

            self.alerts_display_area.addItem(item)

    def _play_alert_sound(self, alert_text: str):
        """Plays appropriate system sound for alert type."""
        if self.mute_action.isChecked() or not self.enable_sounds_action.isChecked():
            return

        if 'warning' in alert_text or 'watch' in alert_text or 'advisory' in alert_text:
            QApplication.beep()

    def _show_desktop_notification(self, title: str, message: str):
        """Displays a desktop notification."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.showMessage(title, message, self.windowIcon(), 10000)

    def _get_weather_icon(self, short_forecast: str) -> QPixmap:
        """Returns a weather icon based on the short forecast string."""
        icons_path = os.path.join(self._get_resources_path(), ICONS_FOLDER_NAME)
        forecast_lower = short_forecast.lower()
        
        icon_map = {
            "sunny": "sunny.png",
            "clear": "sunny.png",
            "mostly sunny": "sunny.png",
            "partly sunny": "partly_cloudy.png",
            "partly cloudy": "partly_cloudy.png",
            "mostly cloudy": "cloudy.png",
            "cloudy": "cloudy.png",
            "showers": "rain.png",
            "rain": "rain.png",
            "thunderstorm": "thunderstorm.png",
            "snow": "snow.png",
            "fog": "fog.png",
            "windy": "windy.png"
        }

        for keyword, icon_file in icon_map.items():
            if keyword in forecast_lower:
                icon_path = os.path.join(icons_path, icon_file)
                if os.path.exists(icon_path):
                    return QPixmap(icon_path)

        # Fallback icon
        fallback_icon_path = os.path.join(icons_path, "unknown.png")
        if os.path.exists(fallback_icon_path):
            return QPixmap(fallback_icon_path)
            
        return QPixmap()

    def _update_hourly_forecast_display(self, forecast_json: Optional[Dict[str, Any]]):
        self._clear_layout(self.hourly_forecast_layout)
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            self.hourly_forecast_layout.addWidget(QLabel("8-Hour forecast data unavailable."), 0, 0)
            return

        periods = forecast_json['properties']['periods'][:8]
        headers = ["Icon", "Time", "Temp", "Feels Like", "Wind", "Precip", "Forecast"]
        for col, header in enumerate(headers):
            self.hourly_forecast_layout.addWidget(QLabel(f"<b>{header}</b>"), 0, col)

        for i, p in enumerate(periods):
            try:
                start_time_str = p.get('startTime', '')
                time_obj = time.strptime(start_time_str.split('T')[1].split('-')[0], "%H:%M:%S")
                formatted_time = time.strftime("%I %p", time_obj).lstrip('0')
                temp = f"{p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}"
                
                # Get feels like temp
                feels_like = p.get('apparentTemperature', {}).get('value')
                if feels_like:
                    feels_like = f"{round(feels_like * 9/5 + 32)}°F"
                else:
                    feels_like = "N/A"

                # Enhanced wind display
                wind_speed = p.get('windSpeed', 'N/A')
                wind_dir = p.get('windDirection', '')
                wind = f"{wind_dir} {wind_speed}" if wind_dir else wind_speed

                # Precipitation chance
                precip = p.get('probabilityOfPrecipitation', {}).get('value', '0')
                precip = f"{precip}%" if precip != '0' else "-"

                short_fc = p.get('shortForecast', 'N/A')
                
                icon_label = QLabel()
                icon_label.setPixmap(self._get_weather_icon(short_fc).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.hourly_forecast_layout.addWidget(icon_label, i + 1, 0)
                self.hourly_forecast_layout.addWidget(QLabel(formatted_time), i + 1, 1)
                self.hourly_forecast_layout.addWidget(QLabel(temp), i + 1, 2)
                self.hourly_forecast_layout.addWidget(QLabel(feels_like), i + 1, 3)
                self.hourly_forecast_layout.addWidget(QLabel(wind), i + 1, 4)
                self.hourly_forecast_layout.addWidget(QLabel(precip), i + 1, 5)
                self.hourly_forecast_layout.addWidget(QLabel(short_fc), i + 1, 6)
            except Exception as e:
                self.log_to_gui(f"Error formatting hourly period: {e}", level="WARNING")

    def _update_daily_forecast_display(self, forecast_json: Optional[Dict[str, Any]]):
        self._clear_layout(self.daily_forecast_layout)
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            self.daily_forecast_layout.addWidget(QLabel("5-Day forecast data unavailable."), 0, 0)
            return

        periods = forecast_json['properties']['periods'][:10]
        headers = ["Icon", "Period", "Temp", "Forecast"]
        for col, header in enumerate(headers):
            self.daily_forecast_layout.addWidget(QLabel(f"<b>{header}</b>"), 0, col)

        for i, p in enumerate(periods):
            try:
                name = p.get('name', 'N/A')
                temp = f"{p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}"
                short_fc = p.get('shortForecast', 'N/A')
                detailed_fc = p.get('detailedForecast', 'N/A')

                icon_label = QLabel()
                icon_label.setPixmap(self._get_weather_icon(short_fc).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.daily_forecast_layout.addWidget(icon_label, i + 1, 0)
                
                name_label = QLabel(name)
                name_label.setToolTip(detailed_fc)
                self.daily_forecast_layout.addWidget(name_label, i + 1, 1)
                self.daily_forecast_layout.addWidget(QLabel(temp), i + 1, 2)
                
                short_fc_label = QLabel(short_fc)
                short_fc_label.setToolTip(detailed_fc)
                self.daily_forecast_layout.addWidget(short_fc_label, i + 1, 3)
            except Exception as e:
                self.log_to_gui(f"Error formatting daily period: {e}", level="WARNING")

    def _clear_layout(self, layout: QLayout):
        if layout is None: return
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _open_preferences_dialog(self):
        current_prefs = {
            "repeater_info": self.current_repeater_info,
            "locations": self.locations,
            "interval_key": self.current_interval_key,
            "announce_alerts": self.announce_alerts_action.isChecked(),
            "auto_refresh_content": self.auto_refresh_action.isChecked(),
            "mute_audio": self.mute_action.isChecked(),
            "enable_sounds": self.enable_sounds_action.isChecked(),
            "enable_desktop_notifications": self.desktop_notification_action.isChecked(),
            "dark_mode_enabled": self.dark_mode_action.isChecked(),
            "show_log": self.show_log_action.isChecked(),
            "show_alerts_area": self.show_alerts_area_action.isChecked(),
            "show_forecasts_area": self.show_forecasts_area_action.isChecked(),
            "log_sort_order": self.current_log_sort_order,
        }

        dialog = SettingsDialog(self, current_settings=current_prefs)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_settings_data()

            locations_changed = self.locations != new_data["locations"]
            interval_changed = self.current_interval_key != new_data["interval_key"]

            self.current_repeater_info = new_data["repeater_info"]
            self.locations = new_data["locations"]
            self.current_interval_key = new_data["interval_key"]

            self._update_location_dropdown()
            self.top_interval_combo.setCurrentText(self.current_interval_key)
            self._update_top_status_bar_display()

            if locations_changed:
                self.log_to_gui(f"Locations updated.", level="INFO")
                self._on_location_selected(self.location_combo.currentIndex())

            if interval_changed:
                self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
                    self.current_interval_key, FALLBACK_INITIAL_CHECK_INTERVAL_MS)
                self.log_to_gui(f"Interval changed to: {self.current_interval_key}", level="INFO")

            if self.announce_alerts_action.isChecked() != new_data["announce_alerts"]:
                self.announce_alerts_action.setChecked(new_data["announce_alerts"])

            if self.auto_refresh_action.isChecked() != new_data["auto_refresh_content"]:
                self.auto_refresh_action.setChecked(new_data["auto_refresh_content"])

            if self.mute_action.isChecked() != new_data["mute_audio"]:
                self.mute_action.setChecked(new_data["mute_audio"])

            if self.enable_sounds_action.isChecked() != new_data["enable_sounds"]:
                self.enable_sounds_action.setChecked(new_data["enable_sounds"])
                
            if self.desktop_notification_action.isChecked() != new_data["enable_desktop_notifications"]:
                self.desktop_notification_action.setChecked(new_data["enable_desktop_notifications"])

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
            self._save_settings()
            self.log_to_gui("Preferences updated.", level="INFO")

    @Slot()
    def perform_check_cycle(self):
        if not (self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()):
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            self.top_countdown_label.setText("Next Check: --:-- (Paused)")
            return

        self.main_check_timer.stop()

        if self.auto_refresh_action.isChecked() and QWebEngineView and self.web_view:
            self.web_view.reload()

        for loc in self.locations:
            self._update_location_data(loc["id"])

        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
        if self.current_check_interval_ms > 0:
            self.main_check_timer.start(self.current_check_interval_ms)

    @Slot(object)
    def _process_and_speak_alerts(self, alerts: List[Any], location_id: str):
        new_alerts_found = False
        high_priority_keywords = ["tornado", "severe thunderstorm", "flash flood warning"]

        for alert in alerts:
            if alert.id not in self.alert_history_manager.seen_alerts:
                new_alerts_found = True
                alert_title_lower = alert.title.lower()
                self.log_to_gui(f"New Alert for {self.get_location_name_by_id(location_id)}: {alert.title}", level="IMPORTANT")

                if any(keyword in alert_title_lower for keyword in high_priority_keywords):
                    self.log_to_gui("High-priority alert detected. Triggering extra notifications.", level="INFO")
                    QApplication.alert(self)

                self._speak_weather_alert(f"For {self.get_location_name_by_id(location_id)}, {alert.title}", alert.summary)
                self.alert_history_manager.add_alert(
                    alert.id,
                    {
                        'time': time.strftime('%Y-%m-%d %H:%M'),
                        'type': alert.title.split(' ')[0],
                        'location': self.get_location_name_by_id(location_id),
                        'summary': alert.summary
                    }
                )

        if not new_alerts_found and alerts:
            self.log_to_gui(f"No new alerts for {self.get_location_name_by_id(location_id)}. Total active: {len(alerts)}.", level="INFO")

        self._speak_repeater_info()

    def log_to_gui(self, message: str, level: str = "INFO"):
        formatted_message = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level.upper()}] {message}"
        if hasattr(self, 'log_area'):
            self.log_area.append(formatted_message)
        else:
            self._log_buffer.append(formatted_message)
        getattr(logging, level.lower(), logging.info)(message)

    def update_status(self, message: str):
        self.status_bar.showMessage(message, 5000)

    def closeEvent(self, event):
        self.log_to_gui("Shutting down...", level="INFO")
        self.main_check_timer.stop()
        self.countdown_timer.stop()
        self.clock_timer.stop()
        self.thread_pool.waitForDone()
        self.alert_history_manager.save_history()
        self._save_settings()
        event.accept()

    # --- TTS Engine ---
    class _DummyEngine:
        def say(self, text, name=None): logging.info(f"TTS (Dummy): {text}")

        def runAndWait(self): pass

        def stop(self): pass

        def isBusy(self): return False

    def _initialize_tts_engine(self):
        try:
            engine = pyttsx3.init()
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
        if hasattr(self, 'top_repeater_label'):
            self.top_repeater_label.setText(f"Repeater: {self.current_repeater_info or 'N/A'}")

    def _apply_loaded_settings_to_ui(self):
        self.announce_alerts_action.setChecked(self.current_announce_alerts_checked)
        self.auto_refresh_action.setChecked(self.current_auto_refresh_content_checked)
        self.mute_action.setChecked(self.current_mute_audio_checked)
        self.enable_sounds_action.setChecked(self.current_enable_sounds)
        self.desktop_notification_action.setChecked(self.current_enable_desktop_notifications)
        self.dark_mode_action.setChecked(self.current_dark_mode_enabled)
        
        # Block signals to prevent toggled slots from firing unnecessarily
        self.show_log_action.blockSignals(True)
        self.show_alerts_area_action.blockSignals(True)
        self.show_forecasts_area_action.blockSignals(True)

        self.show_log_action.setChecked(self.current_show_log_checked)
        self.show_alerts_area_action.setChecked(self.current_show_alerts_area_checked)
        self.show_forecasts_area_action.setChecked(self.current_show_forecasts_area_checked)

        self.show_log_action.blockSignals(False)
        self.show_alerts_area_action.blockSignals(False)
        self.show_forecasts_area_action.blockSignals(False)

        self._update_panel_visibility()

        self._update_location_dropdown()
        self.top_interval_combo.setCurrentText(self.current_interval_key)

        self._update_top_status_bar_display()
        self._update_web_sources_menu()
        self._apply_color_scheme()
        self._apply_log_sort()

        if QWebEngineView and self.web_view:
            self._load_web_view_url(self.current_radar_url)

        self.log_to_gui("Settings applied to UI.", level="INFO")

    def _update_location_dropdown(self):
        self.location_combo.blockSignals(True)
        self.location_combo.clear()
        for loc in self.locations:
            self.location_combo.addItem(loc["name"], loc["id"])
        
        current_index = self.location_combo.findData(self.current_location_id)
        if current_index != -1:
            self.location_combo.setCurrentIndex(current_index)
        self.location_combo.blockSignals(False)

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

    def _update_panel_visibility(self):
        """Centralized function to control visibility of main UI panels."""
        show_alerts = self.show_alerts_area_action.isChecked()
        show_forecasts = self.show_forecasts_area_action.isChecked()
        show_log = self.show_log_action.isChecked()

        self.alerts_forecasts_container.setVisible(show_alerts or show_forecasts)
        self.log_and_web_splitter.widget(1).setVisible(show_log)

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
        self.mute_action.setChecked(checked)
        self.mute_button.setChecked(checked)

        style = self.style()
        if checked:
            self.mute_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted))
            self.mute_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted))
        else:
            self.mute_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
            self.mute_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume))

        self._save_settings()

    def _on_enable_sounds_toggled(self, checked):
        self.current_enable_sounds = checked
        self._save_settings()

    def _on_desktop_notification_toggled(self, checked):
        self.current_enable_desktop_notifications = checked
        self._save_settings()

    def _on_dark_mode_toggled(self, checked):
        self.current_dark_mode_enabled = checked
        self._apply_color_scheme()
        self._save_settings()

    def _on_show_log_toggled(self, checked):
        self.current_show_log_checked = checked
        self._update_panel_visibility()
        self._save_settings()

    def _on_show_alerts_toggled(self, checked):
        self.current_show_alerts_area_checked = checked
        self._update_panel_visibility()
        self._save_settings()

    def _on_show_forecasts_toggled(self, checked):
        self.current_show_forecasts_area_checked = checked
        self._update_panel_visibility()
        self._save_settings()

    def _on_speak_and_reset_button_press(self):
        self._speak_repeater_info()
        self._update_main_timer_state()

    def _show_about_dialog(self):
        AboutDialog(self).exec()

    def _show_alert_history(self):
        history_data = self.alert_history_manager.get_recent_alerts(20)
        dialog = AlertHistoryDialog(history_data, self)
        dialog.exec()

    def _show_github_help(self):
        QDesktopServices.openUrl(QUrl(GITHUB_HELP_URL))

    @Slot(int)
    def _on_location_selected(self, index):
        if index == -1:
            return
        location_id = self.location_combo.itemData(index)
        if location_id != self.current_location_id:
            self.current_location_id = location_id
            self.log_to_gui(f"Selected location: {self.get_current_location_name()}", level="INFO")
            self._update_location_data(self.current_location_id)
            self._save_settings()

    @Slot(str)
    def _on_top_interval_changed(self, new_interval_key: str):
        if new_interval_key and new_interval_key != self.current_interval_key:
            self.current_interval_key = new_interval_key
            self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
                self.current_interval_key, FALLBACK_INITIAL_CHECK_INTERVAL_MS)
            self.log_to_gui(f"Interval changed to: {self.current_interval_key} (from top bar)", level="INFO")
            self._update_main_timer_state()
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
            url_str = action.data()
            self.current_radar_url = url_str
            self._last_valid_radar_text = action.text()
            self._load_web_view_url(url_str)
            self._save_settings()
            self._update_web_sources_menu()

    def _load_web_view_url(self, url_str: str):
        if QWebEngineView and self.web_view:
            if url_str.lower().endswith('.pdf'):
                self.web_view.setHtml(
                    f"<html><body><div style='text-align: center; margin-top: 50px; font-size: 18px; color: grey;'>"
                    f"Loading PDF...<br><br>Opening <a href='{url_str}'>{url_str}</a> in default browser.</div></body></html>"
                )
                QDesktopServices.openUrl(QUrl(url_str))
            else:
                self.web_view.setUrl(QUrl(url_str))
            self.log_to_gui(f"Loaded web view: {url_str}", level="INFO")
        else:
            self.log_to_gui("Web view not available.", level="WARNING")

    def _open_current_in_browser(self):
        if QWebEngineView and self.web_view:
            QDesktopServices.openUrl(QUrl(self.current_radar_url))
            self.log_to_gui(f"Opening {self.current_radar_url} in default browser.", level="INFO")
        else:
            self.log_to_gui("No web view available to open in browser.", level="WARNING")

    def _save_current_web_source(self):
        if not (QWebEngineView and self.web_view):
            self.log_to_gui("No web view available to save.", level="WARNING")
            return

        current_url = self.current_radar_url
        dialog = AddEditSourceDialog(self, current_url=current_url)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data: return
            name, url = data
            if name in self.RADAR_OPTIONS:
                QMessageBox.warning(self, "Duplicate Name", f"A source with the name '{name}' already exists.")
                return
            self.RADAR_OPTIONS[name] = url
            self.current_radar_url = url
            self._last_valid_radar_text = name
            self._save_settings()
            self._update_web_sources_menu()
            self.log_to_gui(f"Added new web source: {name} ({url})", level="INFO")

    def _add_new_web_source(self):
        dialog = AddEditSourceDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data: return
            name, url = data
            if name in self.RADAR_OPTIONS:
                QMessageBox.warning(self, "Duplicate Name", f"A source with the name '{name}' already exists.")
                return
            self.RADAR_OPTIONS[name] = url
            self.current_radar_url = url
            self._last_valid_radar_text = name
            self._load_web_view_url(url)
            self._save_settings()
            self._update_web_sources_menu()
            self.log_to_gui(f"Added new web source: {name} ({url})", level="INFO")

    def _manage_web_sources(self):
        dialog = ManageSourcesDialog(self.RADAR_OPTIONS, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_sources = dialog.get_sources()
            self.RADAR_OPTIONS = new_sources
            if self.current_radar_url not in self.RADAR_OPTIONS.values():
                self.current_radar_url = list(self.RADAR_OPTIONS.values())[0] if self.RADAR_OPTIONS else ""
                self._last_valid_radar_text = list(self.RADAR_OPTIONS.keys())[0] if self.RADAR_OPTIONS else ""
                self._load_web_view_url(self.current_radar_url)
            self._save_settings()
            self._update_web_sources_menu()
            self.log_to_gui("Web sources updated.", level="INFO")

    def _get_display_name_for_url(self, url: str) -> Optional[str]:
        for name, u in self.RADAR_OPTIONS.items():
            if u == url:
                return name
        return None

    def _apply_color_scheme(self):
        stylesheet_file = DARK_STYLESHEET_FILE_NAME if self.current_dark_mode_enabled else LIGHT_STYLESHEET_FILE_NAME
        stylesheet_path = os.path.join(self._get_resources_path(), stylesheet_file)
        try:
            with open(stylesheet_path, 'r') as f:
                stylesheet = f.read()
            self.setStyleSheet(stylesheet)
            self.log_to_gui(f"Applied {'dark' if self.current_dark_mode_enabled else 'light'} theme.", level="INFO")
        except (IOError, OSError) as e:
            self.log_to_gui(f"Error loading stylesheet {stylesheet_path}: {e}", level="WARNING")
            fallback_stylesheet = """
                QWidget { background-color: #ffffff; color: #000000; }
                QTextEdit, QListWidget { background-color: #f0f0f0; }
                QPushButton { background-color: #e0e0e0; border: 1px solid #aaaaaa; }
            """ if not self.current_dark_mode_enabled else """
                QWidget { background-color: #2e2e2e; color: #ffffff; }
                QTextEdit, QListWidget { background-color: #3a3a3a; }
                QPushButton { background-color: #4a4a4a; border: 1px solid #666666; }
            """
            self.setStyleSheet(fallback_stylesheet)
            self.log_to_gui("Applied fallback stylesheet.", level="INFO")

    def _apply_log_sort(self):
        current_text = self.log_area.toPlainText()
        if not current_text:
            return

        lines = current_text.split('\n')
        if self.current_log_sort_order == "chronological":
            pass
        elif self.current_log_sort_order == "ascending":
            lines.sort()
        elif self.current_log_sort_order == "descending":
            lines.sort(reverse=True)

        self.log_area.clear()
        self.log_area.append('\n'.join(lines))

    @Slot()
    def _sort_log_ascending(self):
        self.current_log_sort_order = "ascending"
        self._apply_log_sort()
        self._save_settings()
        self.log_to_gui("Log sorted in ascending order.", level="INFO")

    @Slot()
    def _sort_log_descending(self):
        self.current_log_sort_order = "descending"
        self._apply_log_sort()
        self._save_settings()
        self.log_to_gui("Log sorted in descending order.", level="INFO")

    def _backup_settings(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Backup Settings", "", "JSON Files (*.json);;All Files (*)"
        )
        if file_name:
            try:
                settings_file = os.path.join(self._get_resources_path(), SETTINGS_FILE_NAME)
                if os.path.exists(settings_file):
                    shutil.copy(settings_file, file_name)
                    self.log_to_gui(f"Settings backed up to {file_name}", level="INFO")
                    QMessageBox.information(self, "Backup Successful", f"Settings backed up to:\n{file_name}")
                else:
                    self.log_to_gui("No settings file found to backup.", level="WARNING")
                    QMessageBox.warning(self, "Backup Failed", "No settings file found to backup.")
            except (IOError, OSError) as e:
                self.log_to_gui(f"Error backing up settings: {e}", level="ERROR")
                QMessageBox.critical(self, "Backup Error", f"Failed to backup settings:\n{e}")

    def _restore_settings(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Restore Settings", "", "JSON Files (*.json);;All Files (*)"
        )
        if file_name:
            try:
                with open(file_name, 'r') as f:
                    settings = json.load(f)
                settings_file = os.path.join(self._get_resources_path(), SETTINGS_FILE_NAME)
                with open(settings_file, 'w') as f:
                    json.dump(settings, f, indent=4)
                self.log_to_gui(f"Settings restored from {file_name}", level="INFO")
                QMessageBox.information(self, "Restore Successful", "Settings restored. Restarting application...")
                self._load_settings()
                self._apply_loaded_settings_to_ui()
                self._update_location_data(self.current_location_id)
            except (IOError, OSError, json.JSONDecodeError) as e:
                self.log_to_gui(f"Error restoring settings: {e}", level="ERROR")
                QMessageBox.critical(self, "Restore Error", f"Failed to restore settings:\n{e}")

    def _filter_alerts(self):
        sender = self.sender()
        if sender == self.all_alerts_button:
            for i in range(self.alerts_display_area.count()):
                self.alerts_display_area.item(i).setHidden(False)
            self.warning_button.setChecked(False)
            self.watch_button.setChecked(False)
            self.advisory_button.setChecked(False)
            return

        # Uncheck "All" if another filter is activated
        if sender.isChecked() and self.all_alerts_button.isChecked():
            self.all_alerts_button.setChecked(False)

        # If all filters are unchecked, check "All"
        if not self.warning_button.isChecked() and not self.watch_button.isChecked() and not self.advisory_button.isChecked():
            self.all_alerts_button.setChecked(True)

        show_all = self.all_alerts_button.isChecked()
        show_warning = self.warning_button.isChecked()
        show_watch = self.watch_button.isChecked()
        show_advisory = self.advisory_button.isChecked()

        for i in range(self.alerts_display_area.count()):
            item = self.alerts_display_area.item(i)
            text = item.text().lower()

            show = False
            if show_all:
                show = True
            else:
                if 'warning' in text and show_warning:
                    show = True
                elif 'watch' in text and show_watch:
                    show = True
                elif 'advisory' in text and show_advisory:
                    show = True

            item.setHidden(not show)


# --- Application Entry Point ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create('Fusion'))
    window = WeatherAlertApp()
    window.show()
    sys.exit(app.exec())
