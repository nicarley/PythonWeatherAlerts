import sys
import requests
import feedparser
import pyttsx3
import time
import logging
import os
import json
import shutil  # For file copying

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QMessageBox,
    QStatusBar, QCheckBox, QSplitter, QStyleFactory, QGroupBox, QDialog,
    QDialogButtonBox, QFormLayout, QListWidget, QListWidgetItem,
    QSpacerItem, QSizePolicy, QFileDialog, QFrame  # Added QFrame
)
from PySide6.QtCore import Qt, QTimer, Slot, QUrl, QFile, QTextStream
from PySide6.QtGui import QTextCursor, QIcon, QColor, QDesktopServices, QPalette, QAction, QActionGroup

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None
    logging.warning("PySide6.QtWebEngineWidgets not found. Web view will be disabled.")

versionnumber = "2025.07.03"  # Updated version

# --- Constants ---
FALLBACK_INITIAL_CHECK_INTERVAL_MS = 900 * 1000
FALLBACK_DEFAULT_INTERVAL_KEY = "15 Minutes"
FALLBACK_DEFAULT_AIRPORT_ID = "SLO"
FALLBACK_INITIAL_REPEATER_INFO = ""
GITHUB_HELP_URL = "https://github.com/nicarley/PythonWeatherAlerts#pyweatheralertgui---weather-alert-monitor" # New Constant

DEFAULT_RADAR_OPTIONS = {
    "N.W.S. Radar": "https://radar.weather.gov/",
    "Windy.com": "https://www.windy.com/"
}
FALLBACK_DEFAULT_RADAR_DISPLAY_NAME = "N.W.S. Radar"
FALLBACK_DEFAULT_RADAR_URL = DEFAULT_RADAR_OPTIONS[FALLBACK_DEFAULT_RADAR_DISPLAY_NAME]

FALLBACK_ANNOUNCE_ALERTS_CHECKED = False
FALLBACK_SHOW_LOG_CHECKED = False
FALLBACK_SHOW_ALERTS_AREA_CHECKED = True
FALLBACK_SHOW_FORECASTS_AREA_CHECKED = True
FALLBACK_AUTO_REFRESH_CONTENT_CHECKED = False
FALLBACK_DARK_MODE_ENABLED = False

CHECK_INTERVAL_OPTIONS = {
    "1 Minute": 1 * 60 * 1000, "5 Minutes": 5 * 60 * 1000,
    "10 Minutes": 10 * 60 * 1000, "15 Minutes": 15 * 60 * 1000,
    "30 Minutes": 30 * 60 * 1000, "1 Hour": 60 * 60 * 1000,
}

NWS_STATION_API_URL_TEMPLATE = "https://api.weather.gov/stations/{station_id}"
NWS_POINTS_API_URL_TEMPLATE = "https://api.weather.gov/points/{latitude},{longitude}"
WEATHER_URL_PREFIX = "https://api.weather.gov/alerts/active.atom?point="
WEATHER_URL_SUFFIX = "&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Future%2CExpected"

SETTINGS_FILE_NAME = "settings.txt"
RESOURCES_FOLDER_NAME = "resources"
LIGHT_STYLESHEET_FILE_NAME = "modern.qss"
DARK_STYLESHEET_FILE_NAME = "dark_modern.qss"
ADD_NEW_SOURCE_TEXT = "Add New Source..."
MANAGE_SOURCES_TEXT = "Manage Sources..."
ADD_CURRENT_SOURCE_TEXT = "Add Current View as Source..."

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Dialog Classes (AddEditSourceDialog, GetNameDialog, ManageSourcesDialog remain the same) ---
class AddEditSourceDialog(QDialog):
    def __init__(self, parent=None, current_name=None, current_url=None):
        super().__init__(parent)
        if current_name and current_url:
            self.setWindowTitle("Edit Web Source")
        else:
            self.setWindowTitle("Add New Web Source")
        self.layout = QFormLayout(self)
        self.name_edit = QLineEdit(self)
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("https://example.com/radar_or_page.html")
        if current_name: self.name_edit.setText(current_name)
        if current_url: self.url_edit.setText(current_url)
        self.layout.addRow("Display Name:", self.name_edit)
        self.layout.addRow("URL (Web Page or PDF):", self.url_edit)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        Qt.Orientation.Horizontal, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_data(self):
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        if name and url and (url.startswith("http://") or url.startswith("https://")): return name, url
        return None, None


class GetNameDialog(QDialog):
    def __init__(self, parent=None, url_to_save=""):
        super().__init__(parent)
        self.setWindowTitle("Name This Source")
        self.layout = QFormLayout(self)
        self.name_edit = QLineEdit(self)
        self.url_label = QLabel(f"URL: {url_to_save}")
        self.url_label.setWordWrap(True)
        self.layout.addRow("Display Name:", self.name_edit)
        self.layout.addRow(self.url_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        Qt.Orientation.Horizontal, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)
        self.name_edit.setFocus()

    def get_name(self):
        name = self.name_edit.text().strip()
        return name if name else None


class ManageSourcesDialog(QDialog):
    def __init__(self, radar_options_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Web Sources")
        self.setGeometry(200, 200, 500, 350)
        self.layout = QVBoxLayout(self)
        self.list_widget = QListWidget(self)
        self.list_widget.setAlternatingRowColors(True)
        self.populate_list(radar_options_dict)
        self.layout.addWidget(self.list_widget)
        self.button_layout = QHBoxLayout()
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        self.edit_button = QPushButton("Edit")
        self.delete_button = QPushButton("Delete")
        self.up_button.clicked.connect(self.move_item_up)
        self.down_button.clicked.connect(self.move_item_down)
        self.edit_button.clicked.connect(self.edit_item)
        self.delete_button.clicked.connect(self.delete_item)
        self.button_layout.addWidget(self.up_button)
        self.button_layout.addWidget(self.down_button)
        self.button_layout.addWidget(self.edit_button)
        self.button_layout.addStretch(1)
        self.button_layout.addWidget(self.delete_button)
        self.layout.addLayout(self.button_layout)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        Qt.Orientation.Horizontal, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)
        self.list_widget.currentRowChanged.connect(self.update_button_state)
        self.list_widget.itemDoubleClicked.connect(self.edit_item)
        self.update_button_state(self.list_widget.currentRow())

    def populate_list(self, radar_options_dict):
        self.list_widget.clear()
        for name, url in radar_options_dict.items():
            item = QListWidgetItem(f"{name}  ({url})")
            item.setData(Qt.ItemDataRole.UserRole, {"name": name, "url": url})
            self.list_widget.addItem(item)

    def update_button_state(self, current_row):
        has_selection = current_row >= 0
        self.delete_button.setEnabled(has_selection)
        self.edit_button.setEnabled(has_selection)
        self.up_button.setEnabled(has_selection and current_row > 0)
        self.down_button.setEnabled(has_selection and current_row < self.list_widget.count() - 1)

    def move_item_up(self):
        row = self.list_widget.currentRow()
        if row > 0: item = self.list_widget.takeItem(row); self.list_widget.insertItem(row - 1,
                                                                                       item); self.list_widget.setCurrentRow(
            row - 1)

    def move_item_down(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1: item = self.list_widget.takeItem(row); self.list_widget.insertItem(
            row + 1, item); self.list_widget.setCurrentRow(row + 1)

    def edit_item(self):
        item = self.list_widget.currentItem()
        if not item: return
        data = item.data(Qt.ItemDataRole.UserRole)
        dialog = AddEditSourceDialog(self, data.get("name"), data.get("url"))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, url = dialog.get_data()
            if name and url:
                # Check for name conflict (excluding current item being edited)
                for i in range(self.list_widget.count()):
                    loop_item = self.list_widget.item(i)
                    if loop_item == item: continue
                    if loop_item.data(Qt.ItemDataRole.UserRole).get("name") == name:
                        QMessageBox.warning(self, "Name Conflict", f"The name '{name}' is already in use.");
                        return
                item.setText(f"{name}  ({url})");
                item.setData(Qt.ItemDataRole.UserRole, {"name": name, "url": url})
            else:
                QMessageBox.warning(self, "Invalid Input", "Both name and URL are required.")

    def delete_item(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            name_to_delete = self.list_widget.item(row).data(Qt.ItemDataRole.UserRole).get("name", "this source")
            if QMessageBox.question(self, 'Delete Source', f"Delete '{name_to_delete}'?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.list_widget.takeItem(row)

    def get_sources(self):
        return {self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)["name"]:
                    self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)["url"] for i in
                range(self.list_widget.count())}


class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.current_settings = current_settings if current_settings else {}

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.repeater_entry = QLineEdit(self.current_settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO))
        form_layout.addRow("Repeater Announcement:", self.repeater_entry)

        self.airport_id_entry = QLineEdit(self.current_settings.get("airport_id", FALLBACK_DEFAULT_AIRPORT_ID))
        self.airport_id_entry.setFixedWidth(100)
        airport_id_layout = QHBoxLayout()
        airport_id_layout.addWidget(self.airport_id_entry)
        airport_lookup_label = QLabel()
        airport_lookup_label.setTextFormat(Qt.TextFormat.RichText)
        airport_lookup_label.setText(
            '<a href="https://www.iata.org/en/publications/directories/code-search/">Airport ID Lookup</a>')
        airport_lookup_label.setOpenExternalLinks(True)
        airport_id_layout.addWidget(airport_lookup_label)
        airport_id_layout.addStretch()
        form_layout.addRow("Airport ID:", airport_id_layout)

        self.interval_combobox = QComboBox()
        self.interval_combobox.addItems(CHECK_INTERVAL_OPTIONS.keys())
        self.interval_combobox.setCurrentText(self.current_settings.get("interval_key", FALLBACK_DEFAULT_INTERVAL_KEY))
        form_layout.addRow("Check Interval:", self.interval_combobox)

        layout.addLayout(form_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def get_settings_data(self):
        return {
            "repeater_info": self.repeater_entry.text(),
            "airport_id": self.airport_id_entry.text(),
            "interval_key": self.interval_combobox.currentText()
        }


class WeatherAlertApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Weather Alert Monitor Version {versionnumber}")
        self.setGeometry(100, 100, 850, 780)

        self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()
        self._last_valid_radar_text = FALLBACK_DEFAULT_RADAR_DISPLAY_NAME
        self.current_radar_url = FALLBACK_DEFAULT_RADAR_URL

        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.current_airport_id = FALLBACK_DEFAULT_AIRPORT_ID
        self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
        self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
        self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED
        self.current_show_alerts_area_checked = FALLBACK_SHOW_ALERTS_AREA_CHECKED
        self.current_show_forecasts_area_checked = FALLBACK_SHOW_FORECASTS_AREA_CHECKED
        self.current_auto_refresh_content_checked = FALLBACK_AUTO_REFRESH_CONTENT_CHECKED
        self.current_dark_mode_enabled = FALLBACK_DARK_MODE_ENABLED

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

        if self.is_tts_dummy:
            self.log_to_gui("TTS engine failed. Using fallback.", level="ERROR")
        else:
            self.log_to_gui("TTS engine initialized.", level="INFO")
        self.log_to_gui(f"Monitoring: K{self.current_airport_id}", level="INFO")
        initial_radar_display_name_log = self._get_display_name_for_url(self.current_radar_url) or \
                                         (list(self.RADAR_OPTIONS.keys())[0] if self.RADAR_OPTIONS else "None")
        self.log_to_gui(f"Initial Web Source: {initial_radar_display_name_log} ({self.current_radar_url})",
                        level="INFO")

        self._update_station_forecasts_display()
        self._update_alerts_display_area([])
        self._update_main_timer_state()

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
        else:
            logging.warning(f"Could not load app icon.")

    def _get_resources_path(self):
        base_path = os.path.dirname(os.path.abspath(__file__))
        resources_path = os.path.join(base_path, RESOURCES_FOLDER_NAME)
        if not os.path.exists(resources_path):
            try:
                os.makedirs(resources_path);
                logging.info(f"Created resources directory: {resources_path}")
            except OSError as e:
                logging.error(f"Could not create resources dir {resources_path}: {e}");
                return None
        return resources_path

    def _load_settings(self):
        resources_path = self._get_resources_path()
        if not resources_path: logging.error("Cannot load settings, resources path issue."); return

        settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        settings_loaded_successfully = False
        try:
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
                self.current_repeater_info = settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO)
                self.current_airport_id = settings.get("airport_id", FALLBACK_DEFAULT_AIRPORT_ID)
                self.current_interval_key = settings.get("check_interval_key", FALLBACK_DEFAULT_INTERVAL_KEY)
                loaded_radar_options = settings.get("radar_options_dict", DEFAULT_RADAR_OPTIONS.copy())
                if isinstance(loaded_radar_options, dict) and loaded_radar_options:
                    for default_name, default_url in DEFAULT_RADAR_OPTIONS.items():
                        if default_name not in loaded_radar_options: loaded_radar_options[default_name] = default_url
                    self.RADAR_OPTIONS = loaded_radar_options
                else:
                    self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()
                self.current_radar_url = settings.get("radar_url", FALLBACK_DEFAULT_RADAR_URL)
                if not self._get_display_name_for_url(self.current_radar_url) and self.RADAR_OPTIONS:
                    self.current_radar_url = list(self.RADAR_OPTIONS.values())[0]
                self.current_announce_alerts_checked = settings.get("announce_alerts", FALLBACK_ANNOUNCE_ALERTS_CHECKED)
                self.current_show_log_checked = settings.get("show_log", FALLBACK_SHOW_LOG_CHECKED)
                self.current_show_alerts_area_checked = settings.get("show_alerts_area",
                                                                     FALLBACK_SHOW_ALERTS_AREA_CHECKED)
                self.current_show_forecasts_area_checked = settings.get("show_forecasts_area",
                                                                        FALLBACK_SHOW_FORECASTS_AREA_CHECKED)
                self.current_auto_refresh_content_checked = settings.get("auto_refresh_content",
                                                                         FALLBACK_AUTO_REFRESH_CONTENT_CHECKED)
                self.current_dark_mode_enabled = settings.get("dark_mode_enabled", FALLBACK_DARK_MODE_ENABLED)
                self._last_valid_radar_text = self._get_display_name_for_url(self.current_radar_url) or \
                                              (list(self.RADAR_OPTIONS.keys())[0] if self.RADAR_OPTIONS else "")
                logging.info(f"Settings loaded from {settings_file}")
                settings_loaded_successfully = True
        except (json.JSONDecodeError, IOError, KeyError, IndexError) as e:
            logging.error(f"Error loading settings: {e}. Using defaults.")

        if not settings_loaded_successfully:
            self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
            self.current_airport_id = FALLBACK_DEFAULT_AIRPORT_ID
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
            if not os.path.exists(settings_file): logging.info(f"Settings file not found. Using defaults.")

    @Slot()
    def _save_settings(self):
        resources_path = self._get_resources_path()
        if not resources_path: self.log_to_gui("Cannot save settings, resources path issue.", level="ERROR"); return

        settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        settings = {
            "repeater_info": self.current_repeater_info,
            "airport_id": self.current_airport_id,
            "check_interval_key": self.current_interval_key,
            "radar_options_dict": self.RADAR_OPTIONS,
            "radar_url": self.current_radar_url,
            "announce_alerts": self.announce_alerts_action.isChecked(),
            "show_log": self.show_log_action.isChecked(),
            "show_alerts_area": self.show_alerts_area_action.isChecked(),
            "show_forecasts_area": self.show_forecasts_area_action.isChecked(),
            "auto_refresh_content": self.auto_refresh_action.isChecked(),
            "dark_mode_enabled": self.dark_mode_action.isChecked()
        }
        try:
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            self.log_to_gui(f"Settings saved (Dark Mode: {self.dark_mode_action.isChecked()})", level="INFO")
            self.update_status(f"Settings saved.")
        except (IOError, OSError) as e:
            self.log_to_gui(f"Error saving settings: {e}", level="ERROR")

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)

        # --- Top Status Bar ---
        self.top_status_widget = QWidget()
        top_status_layout = QHBoxLayout(self.top_status_widget)
        top_status_layout.setContentsMargins(5, 3, 5, 3)

        self.top_repeater_label = QLabel("Repeater: N/A")
        self.top_airport_label = QLabel("Airport: N/A")
        self.top_interval_label = QLabel("Interval: N/A")
        self.top_countdown_label = QLabel("Next Check: --:--")

        top_status_layout.addWidget(self.top_repeater_label)
        top_status_layout.addSpacing(20)
        top_status_layout.addWidget(self.top_airport_label)
        top_status_layout.addSpacing(20)
        top_status_layout.addWidget(self.top_interval_label)
        top_status_layout.addStretch(1)
        top_status_layout.addWidget(self.top_countdown_label)

        self.top_status_widget.setObjectName("TopStatusBar")
        main_layout.addWidget(self.top_status_widget)

        # --- Menu Bar ---
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        preferences_action = QAction("&Preferences...", self)
        preferences_action.triggered.connect(self._open_preferences_dialog)
        file_menu.addAction(preferences_action)
        file_menu.addSeparator()
        self.backup_settings_action = QAction("&Backup Settings...", self)
        self.backup_settings_action.triggered.connect(self._backup_settings)
        file_menu.addAction(self.backup_settings_action)
        self.restore_settings_action = QAction("&Restore Settings...", self)
        self.restore_settings_action.triggered.connect(self._restore_settings)
        file_menu.addAction(self.restore_settings_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menu_bar.addMenu("&View")
        self.web_sources_menu = view_menu.addMenu("&Web Sources")

        view_menu.addSeparator()
        self.show_log_action = QAction("Show &Log Panel", self, checkable=True)
        self.show_log_action.triggered.connect(self._on_show_log_toggled)
        view_menu.addAction(self.show_log_action)
        self.show_alerts_area_action = QAction("Show Current &Alerts Area", self, checkable=True)
        self.show_alerts_area_action.triggered.connect(self._on_show_alerts_area_toggled)
        view_menu.addAction(self.show_alerts_area_action)
        self.show_forecasts_area_action = QAction("Show Station &Forecasts Area", self, checkable=True)
        self.show_forecasts_area_action.triggered.connect(self._on_show_forecasts_area_toggled)
        view_menu.addAction(self.show_forecasts_area_action)
        view_menu.addSeparator()
        self.dark_mode_action = QAction("&Enable Dark Mode", self, checkable=True)
        self.dark_mode_action.triggered.connect(self._on_dark_mode_toggled)
        view_menu.addAction(self.dark_mode_action)

        actions_menu = menu_bar.addMenu("&Actions")
        self.announce_alerts_action = QAction("&Announce Alerts & Start Timer", self, checkable=True)
        self.announce_alerts_action.triggered.connect(self._on_announce_alerts_toggled)
        actions_menu.addAction(self.announce_alerts_action)
        self.auto_refresh_action = QAction("Auto-&Refresh Content", self, checkable=True)
        self.auto_refresh_action.triggered.connect(self._on_auto_refresh_content_toggled)
        actions_menu.addAction(self.auto_refresh_action)
        actions_menu.addSeparator()
        self.speak_reset_action = QAction("&Speak Repeater Info & Reset Timer", self)
        self.speak_reset_action.triggered.connect(self._on_speak_and_reset_button_press)
        actions_menu.addAction(self.speak_reset_action)

        # --- Help Menu ---
        help_menu = menu_bar.addMenu("&Help")
        github_help_action = QAction("View Help on GitHub", self)
        github_help_action.triggered.connect(self._show_github_help)
        help_menu.addAction(github_help_action)


        # --- Alerts and Forecasts Layout ---
        alerts_forecasts_layout = QHBoxLayout()
        self.alerts_group = QGroupBox("Current Alerts")
        alerts_layout = QVBoxLayout(self.alerts_group)
        self.alerts_display_area = QTextEdit()
        self.alerts_display_area.setObjectName("AlertsDisplayArea")
        self.alerts_display_area.setReadOnly(True)
        self.alerts_display_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        alerts_layout.addWidget(self.alerts_display_area)
        alerts_forecasts_layout.addWidget(self.alerts_group, 1)

        self.combined_forecast_widget = QGroupBox("Station Forecasts")
        combined_forecast_layout = QHBoxLayout(self.combined_forecast_widget)
        station_hourly_forecast_group = QWidget()
        station_hourly_forecast_layout = QVBoxLayout(station_hourly_forecast_group)
        station_hourly_forecast_layout.setContentsMargins(0, 0, 0, 0)
        station_hourly_forecast_layout.addWidget(QLabel("<b>4-Hour Forecast:</b>"))
        self.station_hourly_forecast_display_area = QTextEdit()
        self.station_hourly_forecast_display_area.setObjectName("StationHourlyForecastArea")
        self.station_hourly_forecast_display_area.setReadOnly(True)
        self.station_hourly_forecast_display_area.setSizePolicy(QSizePolicy.Policy.Expanding,
                                                                QSizePolicy.Policy.Preferred)
        station_hourly_forecast_layout.addWidget(self.station_hourly_forecast_display_area)
        combined_forecast_layout.addWidget(station_hourly_forecast_group, 1)
        station_daily_forecast_group = QWidget()
        station_daily_forecast_layout = QVBoxLayout(station_daily_forecast_group)
        station_daily_forecast_layout.setContentsMargins(0, 0, 0, 0)
        station_daily_forecast_layout.addWidget(QLabel("<b>3-Day Forecast:</b>"))
        self.daily_forecast_display_area = QTextEdit()
        self.daily_forecast_display_area.setObjectName("DailyForecastArea")
        self.daily_forecast_display_area.setReadOnly(True)
        self.daily_forecast_display_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        station_daily_forecast_layout.addWidget(self.daily_forecast_display_area)
        combined_forecast_layout.addWidget(station_daily_forecast_group, 1)
        alerts_forecasts_layout.addWidget(self.combined_forecast_widget, 2)
        main_layout.addLayout(alerts_forecasts_layout)

        # --- Splitter and Log Area ---
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        if QWebEngineView:
            self.web_view = QWebEngineView()
            self.web_view.urlChanged.connect(self._on_webview_url_changed)
            self.splitter.addWidget(self.web_view)
        else:
            self.web_view = QLabel("WebEngineView not available. Please install PySide6 with webengine support.")
            self.web_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.splitter.addWidget(self.web_view)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.splitter.addWidget(self.log_area)
        if QWebEngineView and self.web_view and isinstance(self.web_view, QWebEngineView):
            self.splitter.setStretchFactor(self.splitter.indexOf(self.web_view), 2)
            self.splitter.setStretchFactor(self.splitter.indexOf(self.log_area), 1)
        else:
            self.splitter.setStretchFactor(self.splitter.indexOf(self.log_area), 1)
            if self.web_view: self.splitter.setStretchFactor(self.splitter.indexOf(self.web_view), 0)
        main_layout.addWidget(self.splitter, 1)

        # --- Status Bar (Bottom) ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.update_status("Application started.")

        self._reload_radar_view()

    def _update_top_status_bar_display(self):
        """Updates the labels in the top status bar with current preference values."""
        if hasattr(self, 'top_repeater_label'):
            repeater_text = self.current_repeater_info if self.current_repeater_info else "N/A"
            max_len = 30
            if len(repeater_text) > max_len:
                repeater_text = repeater_text[:max_len - 3] + "..."
            self.top_repeater_label.setText(f"Repeater: {repeater_text}")
            self.top_repeater_label.setToolTip(self.current_repeater_info if self.current_repeater_info else "Not set")

            self.top_airport_label.setText(f"Airport: K{self.current_airport_id if self.current_airport_id else 'N/A'}")
            self.top_interval_label.setText(f"Interval: {self.current_interval_key}")

    def _apply_loaded_settings_to_ui(self):
        """Updates UI elements (menu actions) to reflect currently loaded settings."""
        self.announce_alerts_action.setChecked(self.current_announce_alerts_checked)
        self.show_log_action.setChecked(self.current_show_log_checked)
        self.log_area.setVisible(self.current_show_log_checked)
        self.auto_refresh_action.setChecked(self.current_auto_refresh_content_checked)
        self.dark_mode_action.setChecked(self.current_dark_mode_enabled)
        self.show_alerts_area_action.setChecked(self.current_show_alerts_area_checked)
        if hasattr(self, 'alerts_group'):
            self.alerts_group.setVisible(self.current_show_alerts_area_checked)
        self.show_forecasts_area_action.setChecked(self.current_show_forecasts_area_checked)
        if hasattr(self, 'combined_forecast_widget'):
            self.combined_forecast_widget.setVisible(self.current_show_forecasts_area_checked)

        self._update_web_sources_menu()
        self._update_top_status_bar_display()
        self._update_main_timer_state()
        self._reload_radar_view()
        self.log_to_gui("Settings applied to UI.", level="INFO")

    def _open_preferences_dialog(self):
        current_prefs = {
            "repeater_info": self.current_repeater_info,
            "airport_id": self.current_airport_id,
            "interval_key": self.current_interval_key
        }
        dialog = SettingsDialog(self, current_settings=current_prefs)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_settings_data()
            self.current_repeater_info = new_data["repeater_info"]
            airport_changed = self.current_airport_id != new_data["airport_id"]
            self.current_airport_id = new_data["airport_id"]
            interval_changed = self.current_interval_key != new_data["interval_key"]
            self.current_interval_key = new_data["interval_key"]

            self._update_top_status_bar_display()

            if airport_changed:
                self.log_to_gui(f"Airport ID changed to: K{self.current_airport_id}", level="INFO")
                self._update_station_forecasts_display()
                self.seen_alert_ids.clear()

            if interval_changed:
                self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
                    self.current_interval_key, FALLBACK_INITIAL_CHECK_INTERVAL_MS
                )
                self.log_to_gui(f"Interval changed to: {self.current_interval_key}", level="INFO")
                self._update_main_timer_state()

            self._save_settings()
            self.log_to_gui("Preferences updated.", level="INFO")

    @Slot(bool)
    def _on_dark_mode_toggled(self, checked):
        if checked != self.current_dark_mode_enabled:
            self.log_to_gui(f"Dark Mode {'enabled' if checked else 'disabled'}.", level="INFO")
            self.current_dark_mode_enabled = checked
            self._apply_color_scheme()
            self._save_settings()

    def _apply_color_scheme(self):
        app = QApplication.instance()
        if not app: return

        app.setStyleSheet("")
        qss_file_to_load = ""
        if self.current_dark_mode_enabled:
            qss_file_to_load = DARK_STYLESHEET_FILE_NAME
            self.log_to_gui(f"Attempting to apply Dark theme: {qss_file_to_load}", level="INFO")
        else:
            if sys.platform == "darwin":
                self.log_to_gui("macOS detected and Dark Mode is off. Using native system styling.", level="INFO")
                return
            else:
                qss_file_to_load = LIGHT_STYLESHEET_FILE_NAME
                self.log_to_gui(f"Attempting to apply Light theme: {qss_file_to_load}", level="INFO")

        if not qss_file_to_load: return
        resources_path = self._get_resources_path()
        if not resources_path: self.log_to_gui("Cannot apply stylesheet, resources path issue.", level="ERROR"); return
        qss_file_path = os.path.join(resources_path, qss_file_to_load)
        qss_file = QFile(qss_file_path)
        if qss_file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
            app.setStyleSheet(QTextStream(qss_file).readAll());
            qss_file.close()
            self.log_to_gui(f"Applied stylesheet: {qss_file_to_load}", level="INFO")
        else:
            self.log_to_gui(
                f"Stylesheet {qss_file_to_load} not found: {qss_file_path}. Error: {qss_file.errorString()}",
                level="WARNING")

    @Slot()
    def _show_github_help(self):
        """Loads the GitHub help page into the web_view."""
        if QWebEngineView and self.web_view and isinstance(self.web_view, QWebEngineView):
            self.log_to_gui(f"Loading GitHub help page: {GITHUB_HELP_URL}", level="INFO")
            self.web_view.setUrl(QUrl(GITHUB_HELP_URL))
            # Optionally, bring web_view to front or ensure it's visible if it's part of a tabbed interface etc.
            # For a simple splitter, it should just load.
        else:
            self.log_to_gui("WebEngineView not available. Cannot show GitHub help page in app.", level="WARNING")
            QMessageBox.information(self, "Web View Not Available",
                                    "The embedded web browser is not available to display the help page.\n"
                                    "Please ensure PySide6.QtWebEngineWidgets is installed.")


    @Slot()
    def _backup_settings(self):
        resources_path = self._get_resources_path()
        if not resources_path: QMessageBox.critical(self, "Error", "Resource directory not found."); return
        current_settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        if not os.path.exists(current_settings_file): QMessageBox.information(self, "Backup Settings",
                                                                              "No settings file to backup."); return
        fileName, _ = QFileDialog.getSaveFileName(self, "Backup Settings File",
                                                  f"weather_app_settings_backup_{time.strftime('%Y%m%d_%H%M%S')}.txt",
                                                  "Text Files (*.txt);;All Files (*)")
        if fileName:
            try:
                shutil.copy(current_settings_file, fileName);
                QMessageBox.information(self, "Backup Successful",
                                        f"Settings backed up to:\n{fileName}");
                self.log_to_gui(
                    f"Settings backed up to {fileName}", level="INFO")
            except Exception as e:
                QMessageBox.critical(self, "Backup Failed", f"Could not backup settings: {e}");
                self.log_to_gui(
                    f"Failed to backup settings to {fileName}: {e}", level="ERROR")

    @Slot()
    def _restore_settings(self):
        fileName, _ = QFileDialog.getOpenFileName(self, "Restore Settings File", "",
                                                  "Text Files (*.txt);;All Files (*)")
        if fileName:
            resources_path = self._get_resources_path()
            if not resources_path: QMessageBox.critical(self, "Error", "Resource directory not found."); return
            current_settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
            try:
                shutil.copy(fileName, current_settings_file)
                self.log_to_gui(f"Settings restored from {fileName}. Reloading...", level="INFO")
                self._load_settings()
                self._apply_loaded_settings_to_ui()
                self._apply_color_scheme()
                self._update_station_forecasts_display()
                self.seen_alert_ids.clear()
                self._update_main_timer_state()
                QMessageBox.information(self, "Restore Successful",
                                        f"Settings restored from:\n{fileName}\nApplication UI updated.")
            except Exception as e:
                QMessageBox.critical(self, "Restore Failed", f"Could not restore settings: {e}");
                self.log_to_gui(
                    f"Failed to restore settings from {fileName}: {e}", level="ERROR")

    def _update_web_sources_menu(self):
        if not hasattr(self, 'web_sources_menu'): return

        self.web_sources_menu.clear()
        self.web_source_action_group = QActionGroup(self)

        for name in self.RADAR_OPTIONS.keys():
            action = QAction(name, self, checkable=True)
            action.setData(name)
            action.triggered.connect(
                lambda checked, src_name=name: self._on_radar_source_selected(src_name) if checked else None)
            self.web_sources_menu.addAction(action)
            self.web_source_action_group.addAction(action)
            if self.RADAR_OPTIONS.get(name) == self.current_radar_url:
                action.setChecked(True)
                self._last_valid_radar_text = name

        self.web_sources_menu.addSeparator()
        add_new_action = QAction(ADD_NEW_SOURCE_TEXT, self)
        add_new_action.triggered.connect(lambda: self._on_radar_source_selected(ADD_NEW_SOURCE_TEXT))
        self.web_sources_menu.addAction(add_new_action)
        add_current_action = QAction(ADD_CURRENT_SOURCE_TEXT, self)
        add_current_action.triggered.connect(lambda: self._on_radar_source_selected(ADD_CURRENT_SOURCE_TEXT))
        self.web_sources_menu.addAction(add_current_action)
        manage_action = QAction(MANAGE_SOURCES_TEXT, self)
        manage_action.triggered.connect(lambda: self._on_radar_source_selected(MANAGE_SOURCES_TEXT))
        self.web_sources_menu.addAction(manage_action)

    def _get_display_name_for_url(self, url_to_find):
        for name, url_val in self.RADAR_OPTIONS.items():
            if url_val == url_to_find: return name
        return None

    @Slot(QUrl)
    def _on_webview_url_changed(self, new_qurl):
        if not QWebEngineView or not self.web_view or not isinstance(self.web_view, QWebEngineView): return
        new_url_str = new_qurl.toString()
        if new_url_str == self.current_radar_url or new_url_str == "about:blank" or new_url_str == GITHUB_HELP_URL: # Ignore if it's the help URL
            return
        self.log_to_gui(f"Web Source URL changed in WebView to: {new_url_str}", level="DEBUG")
        self.current_radar_url = new_url_str
        display_name_for_new_url = self._get_display_name_for_url(new_url_str)
        if display_name_for_new_url:
            for action in self.web_source_action_group.actions():
                if action.data() == display_name_for_new_url:
                    if not action.isChecked(): action.setChecked(True)
                    self._last_valid_radar_text = display_name_for_new_url
                    break
        self._save_settings() # Save if user navigates away from a selected source

    @Slot(str)
    def _on_radar_source_selected(self, selected_text_data):
        if not selected_text_data: return

        if selected_text_data == ADD_NEW_SOURCE_TEXT:
            dialog = AddEditSourceDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                name, url = dialog.get_data()
                if name and url:
                    if name in [ADD_NEW_SOURCE_TEXT, MANAGE_SOURCES_TEXT,
                                ADD_CURRENT_SOURCE_TEXT] or name in self.RADAR_OPTIONS:
                        QMessageBox.warning(self, "Invalid Name", f"The name '{name}' is reserved or already exists.")
                        for action in self.web_source_action_group.actions():
                            if action.data() == self._last_valid_radar_text: action.setChecked(True); break
                        return
                    self.RADAR_OPTIONS[name] = url
                    self._update_web_sources_menu()
                    for action in self.web_source_action_group.actions():
                        if action.data() == name: action.setChecked(True); break
                    self.current_radar_url = url
                    self._last_valid_radar_text = name
                    self._reload_radar_view()
                    self._save_settings()
                else:
                    QMessageBox.warning(self, "Invalid Input", "Both name and a valid URL are required.")
            for action in self.web_source_action_group.actions():
                if action.data() == self._last_valid_radar_text: action.setChecked(True); break

        elif selected_text_data == ADD_CURRENT_SOURCE_TEXT:
            current_url_in_view = ""
            if QWebEngineView and self.web_view and isinstance(self.web_view, QWebEngineView):
                current_url_in_view = self.web_view.url().toString() # Get current URL from web_view

            if not current_url_in_view or current_url_in_view == "about:blank" or current_url_in_view == GITHUB_HELP_URL:
                QMessageBox.warning(self, "No Savable URL", "No valid user-navigated URL is currently loaded to save.")
                for action in self.web_source_action_group.actions():
                    if action.data() == self._last_valid_radar_text: action.setChecked(True); break
                return

            existing_name = self._get_display_name_for_url(current_url_in_view)
            if existing_name:
                QMessageBox.information(self, "URL Already Saved",
                                        f"This URL ({current_url_in_view}) is already saved as '{existing_name}'.")
                for action in self.web_source_action_group.actions():
                    if action.data() == existing_name: action.setChecked(True); break
                return
            name_dialog = GetNameDialog(self, url_to_save=current_url_in_view)
            if name_dialog.exec() == QDialog.DialogCode.Accepted:
                name = name_dialog.get_name()
                if name:
                    if name in [ADD_NEW_SOURCE_TEXT, MANAGE_SOURCES_TEXT,
                                ADD_CURRENT_SOURCE_TEXT] or name in self.RADAR_OPTIONS:
                        QMessageBox.warning(self, "Invalid Name", f"The name '{name}' is reserved or already exists.")
                        for action in self.web_source_action_group.actions():
                            if action.data() == self._last_valid_radar_text: action.setChecked(True); break
                        return
                    self.RADAR_OPTIONS[name] = current_url_in_view
                    self._update_web_sources_menu()
                    for action in self.web_source_action_group.actions():
                        if action.data() == name: action.setChecked(True); break
                    self.current_radar_url = current_url_in_view # Update to the newly saved URL
                    self._last_valid_radar_text = name
                    # No need to reload radar view as it's already showing this URL
                    self._save_settings()
                else:
                    QMessageBox.warning(self, "Invalid Input", "A name is required.")
            for action in self.web_source_action_group.actions():
                if action.data() == self._last_valid_radar_text: action.setChecked(True); break

        elif selected_text_data == MANAGE_SOURCES_TEXT:
            dialog = ManageSourcesDialog(self.RADAR_OPTIONS.copy(), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.RADAR_OPTIONS = dialog.get_sources()
                self._update_web_sources_menu()
                current_display_name = self._get_display_name_for_url(self.current_radar_url)
                if not current_display_name and self.RADAR_OPTIONS:
                    first_available_name = list(self.RADAR_OPTIONS.keys())[0]
                    self.current_radar_url = self.RADAR_OPTIONS[first_available_name]
                    self._last_valid_radar_text = first_available_name
                    self.log_to_gui(f"Web source changed to first available: {first_available_name}", level="INFO")
                    self._reload_radar_view()
                    for action in self.web_source_action_group.actions():
                        if action.data() == first_available_name: action.setChecked(True); break
                elif not self.RADAR_OPTIONS:
                    self.current_radar_url = ""
                    self._last_valid_radar_text = ""
                    if hasattr(self, 'web_view') and QWebEngineView and isinstance(self.web_view, QWebEngineView):
                        self.web_view.setUrl(QUrl("about:blank"))
                self._save_settings()
            for action in self.web_source_action_group.actions():
                if action.data() == self._last_valid_radar_text: action.setChecked(True); break

        else:  # Regular web source QAction was triggered
            selected_display_name = selected_text_data
            new_url = self.RADAR_OPTIONS.get(selected_display_name)
            if new_url:
                if new_url != self.current_radar_url:
                    self.current_radar_url = new_url
                    self._last_valid_radar_text = selected_display_name
                    self.log_to_gui(f"Web Source: {selected_display_name} ({self.current_radar_url})", level="INFO")
                    self._reload_radar_view()
                self._save_settings()
            else:
                self.log_to_gui(f"Selected web source '{selected_display_name}' not found in options.", level="WARNING")
                if self._last_valid_radar_text and self._last_valid_radar_text in self.RADAR_OPTIONS:
                    for action in self.web_source_action_group.actions():
                        if action.data() == self._last_valid_radar_text: action.setChecked(True); break
                elif self.RADAR_OPTIONS:
                    first_name = list(self.RADAR_OPTIONS.keys())[0]
                    for action in self.web_source_action_group.actions():
                        if action.data() == first_name: action.setChecked(True); break
                    self.current_radar_url = self.RADAR_OPTIONS[first_name]
                    self._last_valid_radar_text = first_name
                    self._reload_radar_view()

    def _reload_radar_view(self):
        if not self.current_radar_url:
            self.log_to_gui("Current Web Source URL is empty.", level="WARNING")
            if hasattr(self, 'web_view') and QWebEngineView and isinstance(self.web_view,
                                                                           QWebEngineView): self.web_view.setUrl(
                QUrl("about:blank"))
            return
        if self.current_radar_url.lower().endswith(".pdf"):
            self.log_to_gui(f"Opening PDF externally: {self.current_radar_url}", level="INFO")
            if hasattr(self, 'web_view') and QWebEngineView and isinstance(self.web_view, QWebEngineView):
                self.web_view.setHtml(
                    f"<div style='text-align:center; padding:20px;'><h3>PDF Document</h3><p>Opening PDF externally: <a href='{self.current_radar_url}'>{self.current_radar_url}</a></p></div>")
            if not QDesktopServices.openUrl(QUrl(self.current_radar_url)):
                self.log_to_gui(f"Could not automatically open PDF: {self.current_radar_url}", level="ERROR")
                QMessageBox.warning(self, "Open PDF Failed", f"Could not open PDF. Link: {self.current_radar_url}")
            return
        if QWebEngineView and hasattr(self, 'web_view') and isinstance(self.web_view, QWebEngineView):
            if self.web_view.url().toString() != self.current_radar_url:
                self.log_to_gui(f"Loading web content: {self.current_radar_url}", level="DEBUG");
                self.web_view.setUrl(QUrl(self.current_radar_url))
        elif not QWebEngineView:
            self.log_to_gui("WebEngineView not available.", level="WARNING")

    def _initialize_tts_engine(self):
        try:
            engine = pyttsx3.init();
            return engine if engine else self._DummyEngine()
        except Exception as e:
            logging.error(f"TTS engine init failed: {e}.");
            return self._DummyEngine()

    class _DummyEngine:
        def say(self, text, name=None): logging.info(f"TTS (Fallback): {text}")

        def runAndWait(self): pass

        def stop(self): pass

        def isBusy(self): return False

        def getProperty(self, name): return None

        def setProperty(self, name, value): pass

    def log_to_gui(self, message, level="INFO"):
        formatted_message = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {message}"
        cursor = self.log_area.textCursor();
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.log_area.setTextCursor(cursor);
        self.log_area.insertPlainText(formatted_message + "\n")
        getattr(logging, level.lower(), logging.info)(message)

    def update_status(self, message):
        self.status_bar.showMessage(message)

    def _format_time(self, total_seconds):
        if total_seconds < 0: total_seconds = 0
        minutes, seconds = divmod(int(total_seconds), 60);
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes:02d}:{seconds:02d}"

    @Slot()
    def _update_countdown_display(self):
        if self.remaining_time_seconds > 0: self.remaining_time_seconds -= 1

        status_text = ""
        if not (self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()) and \
                self.remaining_time_seconds <= 0:
            status_text = "Next Check: --:-- (Paused)"
        else:
            status_text = f"Next Check: {self._format_time(self.remaining_time_seconds)}"

        if hasattr(self, 'top_countdown_label'):
            self.top_countdown_label.setText(status_text)

    def _reset_and_start_countdown(self, total_seconds_for_interval):
        self.countdown_timer.stop()
        self.remaining_time_seconds = total_seconds_for_interval

        is_active = (self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked())

        status_text = ""
        if is_active and total_seconds_for_interval > 0:
            status_text = f"Next Check: {self._format_time(self.remaining_time_seconds)}"
            self.countdown_timer.start(1000)
        else:
            status_text = "Next Check: --:-- (Paused)"
            self.countdown_timer.stop()
            if self.remaining_time_seconds > 0 and not is_active: # Ensure countdown resets if paused mid-way
                 self.remaining_time_seconds = 0


        if hasattr(self, 'top_countdown_label'):
            self.top_countdown_label.setText(status_text)

    @Slot(bool)
    def _on_show_log_toggled(self, checked):
        self.log_area.setVisible(checked)
        self.current_show_log_checked = checked
        self.log_to_gui(f"Log display {'en' if checked else 'dis'}abled.", level="DEBUG")
        self._save_settings()

    @Slot(bool)
    def _on_show_alerts_area_toggled(self, checked):
        if hasattr(self, 'alerts_group'): self.alerts_group.setVisible(checked)
        self.current_show_alerts_area_checked = checked
        self.log_to_gui(f"Current Alerts display {'en' if checked else 'dis'}abled.", level="DEBUG")
        self._save_settings()

    @Slot(bool)
    def _on_show_forecasts_area_toggled(self, checked):
        if hasattr(self, 'combined_forecast_widget'): self.combined_forecast_widget.setVisible(checked)
        self.current_show_forecasts_area_checked = checked
        self.log_to_gui(f"Station Forecasts display {'en' if checked else 'dis'}abled.", level="DEBUG")
        self._save_settings()

    def _update_main_timer_state(self):
        announce_active = self.announce_alerts_action.isChecked()
        refresh_active = self.auto_refresh_action.isChecked()
        if announce_active or refresh_active:
            if not self.main_check_timer.isActive():
                self.log_to_gui("Timed checks starting/resuming.", level="INFO")
                self.update_status("Timed checks active. Starting check cycle...")
                self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
                QTimer.singleShot(100, self.perform_check_cycle)
            else:
                self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
        else:
            self.log_to_gui("All timed activities disabled.", level="INFO")
            self.update_status("Timed checks paused.")
            self.main_check_timer.stop();
            self.countdown_timer.stop()
            if hasattr(self, 'top_countdown_label'):
                self.top_countdown_label.setText("Next Check: --:-- (Paused)")

    @Slot(bool)
    def _on_announce_alerts_toggled(self, checked):
        self.current_announce_alerts_checked = checked
        self.log_to_gui(f"Alert announcements {'enabled' if checked else 'disabled'}.", level="INFO")
        self._update_main_timer_state()
        self._save_settings()

    @Slot(bool)
    def _on_auto_refresh_content_toggled(self, checked):
        self.current_auto_refresh_content_checked = checked
        self.log_to_gui(f"Auto-refresh content {'enabled' if checked else 'disabled'}.", level="INFO")
        self._update_main_timer_state()
        self._save_settings()

    def _fetch_station_coordinates(self, airport_id_input, log_errors=True):
        if not airport_id_input:
            if log_errors: self.log_to_gui("Airport ID empty.", level="ERROR"); return None
        nws_station_id = "K" + airport_id_input.upper()
        station_url = NWS_STATION_API_URL_TEMPLATE.format(station_id=nws_station_id)
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (your.email@example.com)',
                   'Accept': 'application/geo+json'}
        self.log_to_gui(f"Fetching coords for {nws_station_id} from {station_url}", level="DEBUG")
        try:
            response = requests.get(station_url, headers=headers, timeout=10);
            response.raise_for_status();
            data = response.json()
            geometry = data.get('geometry')
            if geometry and geometry.get('type') == 'Point':
                coords = geometry.get('coordinates')
                if coords and len(coords) == 2: self.log_to_gui(
                    f"Coords for {nws_station_id}: Lat={coords[1]}, Lon={coords[0]}", level="INFO"); return coords[1], \
                    coords[0]
            if log_errors: self.log_to_gui(f"Could not parse coords for {nws_station_id}.", level="ERROR"); return None
        except requests.exceptions.HTTPError as e:
            if log_errors: self.log_to_gui(f"HTTP error for {nws_station_id}: {e}", level="ERROR"); self.update_status(
                f"Error: NWS Station 'K{airport_id_input}' not found." if e.response and e.response.status_code == 404 else f"Error: NWS data for 'K{airport_id_input}'.")
            return None
        except requests.exceptions.RequestException as e:
            if log_errors: self.log_to_gui(f"Network error for {nws_station_id}: {e}",
                                           level="ERROR"); self.update_status(f"Error: Network issue for station data.")
            return None
        except ValueError:
            if log_errors: self.log_to_gui(f"Invalid JSON for {nws_station_id}.", level="ERROR"); self.update_status(
                f"Error: Invalid NWS station data.")
            return None
        except Exception as e:
            if log_errors: self.log_to_gui(f"Unexpected error for {nws_station_id} coords: {e}", level="ERROR")
            return None

    def _fetch_gridpoint_properties(self, latitude, longitude, log_errors=True):
        if latitude is None or longitude is None: return None
        points_url = NWS_POINTS_API_URL_TEMPLATE.format(latitude=latitude, longitude=longitude)
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (your.email@example.com)',
                   'Accept': 'application/geo+json'}
        self.log_to_gui(f"Fetching gridpoint from: {points_url}", level="DEBUG")
        try:
            response = requests.get(points_url, headers=headers, timeout=10);
            response.raise_for_status();
            return response.json()
        except requests.exceptions.RequestException as e:
            if log_errors: self.log_to_gui(f"Error fetching gridpoint: {e}", level="ERROR"); return None
        except ValueError:
            if log_errors: self.log_to_gui(f"Invalid JSON from gridpoint.", level="ERROR"); return None

    def _fetch_forecast_data_from_url(self, forecast_url, log_errors=True):
        if not forecast_url: return None
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (your.email@example.com)',
                   'Accept': 'application/geo+json'}
        self.log_to_gui(f"Fetching forecast: {forecast_url}", level="DEBUG")
        try:
            response = requests.get(forecast_url, headers=headers, timeout=10);
            response.raise_for_status();
            return response.json()
        except requests.exceptions.RequestException as e:
            if log_errors: self.log_to_gui(f"Error fetching forecast from {forecast_url}: {e}",
                                           level="ERROR"); return None
        except ValueError:
            if log_errors: self.log_to_gui(f"Invalid JSON for forecast from {forecast_url}.",
                                           level="ERROR"); return None

    def _format_station_hourly_forecast_display(self, forecast_json):
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json[
            'properties']: return "4-Hour forecast data unavailable."
        periods = forecast_json['properties']['periods']
        display_text = [
            f"{p.get('startTime', '').split('T')[1].split(':')[0:2][0]}:{p.get('startTime', '').split('T')[1].split(':')[0:2][1]}: {p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}, {p.get('shortForecast', 'N/A')}"
            for i, p in enumerate(periods) if i < 4]
        return "\n".join(display_text) if display_text else "No 4-hour forecast periods found."

    def _format_daily_forecast_display(self, forecast_json):
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json[
            'properties']: return "3-Day forecast data unavailable."
        periods = forecast_json['properties']['periods']
        display_text = []
        for p in periods[:6]: name = p.get('name', 'N/A'); temp_label = "High" if "High" in name or p.get("isDaytime",
                                                                                                          False) else "Low"; temp = f"{p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}"; short_fc = p.get(
            'shortForecast', 'N/A'); display_text.append(
            f"{name.replace(' Night', ' Nt')}: {temp_label} {temp}, {short_fc}")
        return "\n".join(display_text) if display_text else "No 3-day forecast periods found."

    def _update_station_forecasts_display(self):
        airport_id = self.current_airport_id
        if not airport_id:
            self.station_hourly_forecast_display_area.setText("Airport ID empty.");
            self.daily_forecast_display_area.setText("Airport ID empty.")
            self.station_hourly_forecast_display_area.updateGeometry();
            self.daily_forecast_display_area.updateGeometry();
            return
        self.station_hourly_forecast_display_area.setText(f"Fetching 4hr forecast for K{airport_id}...");
        self.daily_forecast_display_area.setText(f"Fetching 3-day forecast for K{airport_id}...")
        self.station_hourly_forecast_display_area.document().adjustSize();
        self.station_hourly_forecast_display_area.updateGeometry()
        self.daily_forecast_display_area.document().adjustSize();
        self.daily_forecast_display_area.updateGeometry();
        QApplication.processEvents()
        coords = self._fetch_station_coordinates(airport_id, log_errors=False)
        if not coords:
            msg = f"Could not get coords for K{airport_id}.";
            self.station_hourly_forecast_display_area.setText(msg);
            self.daily_forecast_display_area.setText(msg)
            self.station_hourly_forecast_display_area.document().adjustSize();
            self.station_hourly_forecast_display_area.updateGeometry()
            self.daily_forecast_display_area.document().adjustSize();
            self.daily_forecast_display_area.updateGeometry();
            return
        lat, lon = coords
        grid_props = self._fetch_gridpoint_properties(lat, lon)
        if not grid_props or 'properties' not in grid_props:
            msg = f"Could not get forecast URLs for K{airport_id}.";
            self.station_hourly_forecast_display_area.setText(msg);
            self.daily_forecast_display_area.setText(msg)
            self.station_hourly_forecast_display_area.document().adjustSize();
            self.station_hourly_forecast_display_area.updateGeometry()
            self.daily_forecast_display_area.document().adjustSize();
            self.daily_forecast_display_area.updateGeometry();
            return
        props = grid_props['properties']
        hourly_url = props.get('forecastHourly')
        if hourly_url:
            hourly_json = self._fetch_forecast_data_from_url(
                hourly_url);
            self.station_hourly_forecast_display_area.setText(
                self._format_station_hourly_forecast_display(
                    hourly_json) if hourly_json else f"Could not get 4hr forecast for K{airport_id}.")
        else:
            self.station_hourly_forecast_display_area.setText(f"4hr forecast URL not found for K{airport_id}.")
        self.station_hourly_forecast_display_area.document().adjustSize();
        self.station_hourly_forecast_display_area.updateGeometry()
        daily_url = props.get('forecast')
        if daily_url:
            daily_json = self._fetch_forecast_data_from_url(daily_url);
            self.daily_forecast_display_area.setText(
                self._format_daily_forecast_display(
                    daily_json) if daily_json else f"Could not get 3-day forecast for K{airport_id}.")
        else:
            self.daily_forecast_display_area.setText(f"3-day forecast URL not found for K{airport_id}.")
        self.daily_forecast_display_area.document().adjustSize();
        self.daily_forecast_display_area.updateGeometry()

    def _get_current_weather_url(self, log_errors=True):
        airport_id = self.current_airport_id
        if not airport_id:
            if log_errors: self.log_to_gui("Airport ID empty for alert URL.", level="ERROR"); self.update_status(
                "Error: Airport ID empty.")
            return None
        coords = self._fetch_station_coordinates(airport_id, log_errors=log_errors)
        if coords: return f"{WEATHER_URL_PREFIX}{coords[0]}%2C{coords[1]}{WEATHER_URL_SUFFIX}"
        if log_errors: self.log_to_gui(f"Failed to get coords for K{airport_id} (alerts).", level="ERROR"); return None

    def _get_alerts(self, url):
        if not url: return []
        self.log_to_gui(f"Fetching alerts: {url}", level="DEBUG")
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (your.email@example.com)'}
        try:
            response = requests.get(url, headers=headers,
                                    timeout=10);
            response.raise_for_status();
            feed = feedparser.parse(
                response.content);
            self.log_to_gui(f"Fetched {len(feed.entries)} entries.",
                            level="DEBUG");
            return feed.entries
        except requests.exceptions.Timeout:
            self.log_to_gui(f"Timeout fetching alerts.", level="ERROR")
        except requests.exceptions.HTTPError as e:
            self.log_to_gui(f"HTTP error for alerts: {e}", level="ERROR")
        except requests.exceptions.RequestException as e:
            self.log_to_gui(f"Error fetching alerts: {e}", level="ERROR")
        return []

    def _update_alerts_display_area(self, alerts):
        self.alerts_display_area.clear();
        airport_id = self.current_airport_id
        loc_name = f"K{airport_id}" if airport_id else "selected location"
        if not alerts:
            self.alerts_display_area.setText(f"No active alerts for {loc_name}.")
        else:
            html_lines = [
                f"<strong style='color:{'red' if 'warning' in a.get('title', '').lower() else 'orange' if 'watch' in a.get('title', '').lower() else 'blue' if 'advisory' in a.get('title', '').lower() else 'black'};'>{a.get('title', 'N/A')}</strong>"
                for a in alerts];
            self.alerts_display_area.setHtml("<br>".join(html_lines))
        self.alerts_display_area.document().adjustSize();
        self.alerts_display_area.updateGeometry()

    def _speak_message_internal(self, text_to_speak, log_prefix="Spoken"):
        if not text_to_speak: return
        try:
            self.tts_engine.say(text_to_speak);
            self.tts_engine.runAndWait();
            self.log_to_gui(
                f"{log_prefix}: {text_to_speak}", level="INFO")
        except Exception as e:
            self.log_to_gui(f"TTS error for '{text_to_speak}': {e}", level="ERROR")

    def _speak_weather_alert(self, alert_title, alert_summary):
        msg = f"Weather Alert: {alert_title}. Details: {alert_summary}"
        if self.current_repeater_info: msg += f". {self.current_repeater_info}"
        self._speak_message_internal(msg, log_prefix="Spoken Alert")

    def _speak_repeater_info(self):
        if self.current_repeater_info: self._speak_message_internal(self.current_repeater_info)

    @Slot()
    def _on_speak_and_reset_button_press(self):
        self.log_to_gui("Speak & Reset pressed.", level="INFO")
        if self.announce_alerts_action.isChecked(): self._speak_repeater_info()
        self._update_main_timer_state()
        if self.main_check_timer.isActive():
            QTimer.singleShot(100, self.perform_check_cycle);
            self.update_status(
                f"Manual reset. Next check ~{self.current_check_interval_ms // 60000}m.")
        else:
            self.update_status("Repeater info not spoken (Announce Alerts is off). Timed checks paused.")

    @Slot()
    def perform_check_cycle(self):
        if not self.announce_alerts_action.isChecked() and not self.auto_refresh_action.isChecked():
            self.main_check_timer.stop();
            self.countdown_timer.stop();
            if hasattr(self, 'top_countdown_label'): self.top_countdown_label.setText("Next Check: --:-- (Paused)")
            self.log_to_gui("All timed activities disabled. Skipping check.", level="DEBUG");
            return
        self.main_check_timer.stop()
        self._reload_radar_view();
        self._update_station_forecasts_display()
        airport_id = self.current_airport_id
        self.log_to_gui(f"Performing periodic check for K{airport_id}...", level="INFO")
        self.update_status(f"Checking K{airport_id}... Last: {time.strftime('%H:%M:%S')}")
        if self.announce_alerts_action.isChecked():
            alert_url = self._get_current_weather_url();
            alerts = self._get_alerts(alert_url) if alert_url else []
            self._update_alerts_display_area(alerts)
            new_alerts_found = False
            for alert in alerts:
                if not all(hasattr(alert, attr) for attr in ['id', 'title', 'summary']): self.log_to_gui(
                    f"Malformed alert: {alert}", level="WARNING"); continue
                if alert.id not in self.seen_alert_ids: new_alerts_found = True; self.log_to_gui(
                    f"New Alert: {alert.title}", level="IMPORTANT"); self._speak_weather_alert(alert.title,
                                                                                               alert.summary); self.seen_alert_ids.add(
                    alert.id)
            if not new_alerts_found and alert_url and alerts:
                self.log_to_gui(f"No new alerts. Active: {len(alerts)}. Seen: {len(self.seen_alert_ids)}.",
                                level="INFO")
            elif not alerts and alert_url:
                self.log_to_gui(f"No active alerts for K{airport_id}.", level="INFO")
            self._speak_repeater_info()
        self.update_status(f"Check complete. Next in ~{self.current_check_interval_ms // 60000}m.")
        self.log_to_gui(f"Waiting {self.current_check_interval_ms // 1000}s for next cycle.", level="INFO")
        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
        if self.current_check_interval_ms > 0 and (
                self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()):
            self.main_check_timer.start(self.current_check_interval_ms)

    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Quit', "Quit Weather Alert Monitor?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log_to_gui("Shutting down...", level="INFO");
            self.main_check_timer.stop();
            self.countdown_timer.stop()
            if hasattr(self.tts_engine, 'stop') and not self.is_tts_dummy:
                try:
                    if self.tts_engine.isBusy(): self.tts_engine.stop()
                except Exception as e:
                    logging.error(f"TTS stop error: {e}")
            event.accept()
        else:
            event.ignore()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if sys.platform == "darwin":
        logging.info("macOS detected. Using default Qt platform styling as base.")
    elif "Fusion" in QStyleFactory.keys():
        app.setStyle(QStyleFactory.create("Fusion"));
        logging.info("Applied Fusion style as base.")
    main_win = WeatherAlertApp()
    main_win._apply_color_scheme()  # Apply initial color scheme
    main_win.show()
    sys.exit(app.exec())