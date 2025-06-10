import sys
import requests
import feedparser
import pyttsx3
import time
import logging
import os
import json
import shutil # For file copying

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QMessageBox,
    QStatusBar, QCheckBox, QSplitter, QStyleFactory, QGroupBox, QDialog,
    QDialogButtonBox, QFormLayout, QListWidget, QListWidgetItem,
    QSpacerItem, QSizePolicy, QFileDialog
)
from PySide6.QtCore import Qt, QTimer, Slot, QUrl, QFile, QTextStream
from PySide6.QtGui import QTextCursor, QIcon, QColor, QDesktopServices

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None
    logging.warning("PySide6.QtWebEngineWidgets not found. Web view will be disabled.")


versionnumber = "2025.06.10"

# --- Constants ---
FALLBACK_INITIAL_CHECK_INTERVAL_MS = 900 * 1000
FALLBACK_DEFAULT_INTERVAL_KEY = "15 Minutes"
FALLBACK_DEFAULT_AIRPORT_ID = "SLO"
FALLBACK_INITIAL_REPEATER_INFO = ""

DEFAULT_RADAR_OPTIONS = {
    "N.W.S. Radar": "https://radar.weather.gov/",
    "Windy.com": "https://www.windy.com/"
}
FALLBACK_DEFAULT_RADAR_DISPLAY_NAME = "N.W.S. Radar"
FALLBACK_DEFAULT_RADAR_URL = DEFAULT_RADAR_OPTIONS[FALLBACK_DEFAULT_RADAR_DISPLAY_NAME]

FALLBACK_ANNOUNCE_ALERTS_CHECKED = False
FALLBACK_SHOW_LOG_CHECKED = False
FALLBACK_SHOW_ALERTS_AREA_CHECKED = True  # New
FALLBACK_SHOW_FORECASTS_AREA_CHECKED = True # New


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
STYLESHEET_FILE_NAME = "modern.qss"
ADD_NEW_SOURCE_TEXT = "Add New Source..."
MANAGE_SOURCES_TEXT = "Manage Sources..."
ADD_CURRENT_SOURCE_TEXT = "Add Current View as Source..."

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

        if current_name:
            self.name_edit.setText(current_name)
        if current_url:
            self.url_edit.setText(current_url)

        self.layout.addRow("Display Name:", self.name_edit)
        self.layout.addRow("URL (Web Page or PDF):", self.url_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_data(self):
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        if name and url and (url.startswith("http://") or url.startswith("https://")):
            return name, url
        return None, None

class GetNameDialog(QDialog):
    """Simple dialog to get a name for a pre-filled URL."""
    def __init__(self, parent=None, url_to_save=""):
        super().__init__(parent)
        self.setWindowTitle("Name This Source")
        self.layout = QFormLayout(self)

        self.name_edit = QLineEdit(self)
        self.url_label = QLabel(f"URL: {url_to_save}")
        self.url_label.setWordWrap(True)

        self.layout.addRow("Display Name:", self.name_edit)
        self.layout.addRow(self.url_label)


        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal, self
        )
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

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

        self.list_widget.currentRowChanged.connect(self.update_button_state)
        self.list_widget.itemDoubleClicked.connect(self.edit_item)
        self.update_button_state(self.list_widget.currentRow())

    def populate_list(self, radar_options_dict):
        self.list_widget.clear()
        for name, url in radar_options_dict.items():
            item_text = f"{name}  ({url})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, {"name": name, "url": url})
            self.list_widget.addItem(item)

    def update_button_state(self, current_row):
        has_selection = current_row >= 0
        self.delete_button.setEnabled(has_selection)
        self.edit_button.setEnabled(has_selection)
        self.up_button.setEnabled(has_selection and current_row > 0)
        self.down_button.setEnabled(has_selection and current_row < self.list_widget.count() - 1)

    def move_item_up(self):
        current_row = self.list_widget.currentRow()
        if current_row > 0:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row - 1, item)
            self.list_widget.setCurrentRow(current_row - 1)

    def move_item_down(self):
        current_row = self.list_widget.currentRow()
        if current_row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row + 1, item)
            self.list_widget.setCurrentRow(current_row + 1)

    def edit_item(self):
        current_item = self.list_widget.currentItem()
        if not current_item:
            return

        item_data = current_item.data(Qt.ItemDataRole.UserRole)
        current_name = item_data.get("name")
        current_url = item_data.get("url")

        dialog = AddEditSourceDialog(self, current_name, current_url)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_name, new_url = dialog.get_data()
            if new_name and new_url:
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    if item == current_item:
                        continue
                    existing_item_data = item.data(Qt.ItemDataRole.UserRole)
                    if existing_item_data and existing_item_data.get("name") == new_name:
                        QMessageBox.warning(self, "Name Conflict",
                                            f"The name '{new_name}' is already in use by another source.")
                        return
                current_item.setText(f"{new_name}  ({new_url})")
                current_item.setData(Qt.ItemDataRole.UserRole, {"name": new_name, "url": new_url})
            else:
                QMessageBox.warning(self, "Invalid Input", "Both name and a valid URL are required for editing.")

    def delete_item(self):
        current_row = self.list_widget.currentRow()
        if current_row >= 0:
            item_data = self.list_widget.currentItem().data(Qt.ItemDataRole.UserRole)
            name_to_delete = item_data.get("name", "this source")
            reply = QMessageBox.question(self, 'Delete Source',
                                         f"Are you sure you want to delete '{name_to_delete}'?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.list_widget.takeItem(current_row)

    def get_sources(self):
        sources = {}
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item_data = item.data(Qt.ItemDataRole.UserRole)
            name = item_data.get("name")
            url = item_data.get("url")
            if name and url:
                sources[name] = url
        return sources


class WeatherAlertApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Weather Alert Monitor Version {versionnumber}")
        self.setGeometry(100, 100, 850, 980)

        self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()
        self._last_valid_radar_text = FALLBACK_DEFAULT_RADAR_DISPLAY_NAME

        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.current_airport_id = FALLBACK_DEFAULT_AIRPORT_ID
        self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
        self.current_radar_url = FALLBACK_DEFAULT_RADAR_URL
        self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
        self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED
        self.current_show_alerts_area_checked = FALLBACK_SHOW_ALERTS_AREA_CHECKED # New
        self.current_show_forecasts_area_checked = FALLBACK_SHOW_FORECASTS_AREA_CHECKED # New


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

        self.log_area.setVisible(self.current_show_log_checked)
        self.show_log_checkbox.setChecked(self.current_show_log_checked)
        self.announce_alerts_checkbox.setChecked(self.current_announce_alerts_checked)

        # Set initial visibility for alerts and forecasts areas
        if hasattr(self, 'alerts_group'):
            self.alerts_group.setVisible(self.current_show_alerts_area_checked)
        if hasattr(self, 'combined_forecast_widget'):
            self.combined_forecast_widget.setVisible(self.current_show_forecasts_area_checked)

        if hasattr(self, 'show_alerts_area_checkbox'):
            self.show_alerts_area_checkbox.setChecked(self.current_show_alerts_area_checked)
        if hasattr(self, 'show_forecasts_area_checkbox'):
            self.show_forecasts_area_checkbox.setChecked(self.current_show_forecasts_area_checked)


        if self.is_tts_dummy:
            self.log_to_gui("TTS engine failed. Using fallback.", level="ERROR")
        else:
            self.log_to_gui("TTS engine initialized.", level="INFO")

        self.log_to_gui(
            f"Monitoring: K{self.airport_id_entry.text()}", level="INFO")

        initial_radar_display_name_log = self._get_display_name_for_url(self.current_radar_url)
        if not initial_radar_display_name_log and self.RADAR_OPTIONS:
            initial_radar_display_name_log = list(self.RADAR_OPTIONS.keys())[0]

        self.log_to_gui(f"Initial Web Source: {initial_radar_display_name_log} ({self.current_radar_url})",
                        level="INFO")

        self._update_station_forecasts_display()
        self._update_alerts_display_area([])

        if self.announce_alerts_checkbox.isChecked():
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(1000, self.perform_check_cycle)
        else:
            self.log_to_gui("Alerts paused. Check box to start.", level="INFO")
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
        else:
            logging.warning(f"Could not load app icon.")

    def _get_resources_path(self):
        base_path = os.path.dirname(os.path.abspath(__file__))
        resources_path = os.path.join(base_path, RESOURCES_FOLDER_NAME)
        if not os.path.exists(resources_path):
            try:
                os.makedirs(resources_path)
                logging.info(f"Created resources directory: {resources_path}")
            except OSError as e:
                logging.error(f"Could not create resources dir {resources_path}: {e}")
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
                self.current_airport_id = settings.get("airport_id", FALLBACK_DEFAULT_AIRPORT_ID)
                self.current_interval_key = settings.get("check_interval_key", FALLBACK_DEFAULT_INTERVAL_KEY)

                loaded_radar_options = settings.get("radar_options_dict", DEFAULT_RADAR_OPTIONS.copy())
                if isinstance(loaded_radar_options, dict) and loaded_radar_options:
                    for default_name, default_url in DEFAULT_RADAR_OPTIONS.items():
                        if default_name not in loaded_radar_options:
                            loaded_radar_options[default_name] = default_url
                    self.RADAR_OPTIONS = loaded_radar_options
                else:
                    self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()

                self.current_radar_url = settings.get("radar_url", FALLBACK_DEFAULT_RADAR_URL)
                if not self._get_display_name_for_url(self.current_radar_url) and self.RADAR_OPTIONS:
                    first_available_url = list(self.RADAR_OPTIONS.values())[0]
                    self.current_radar_url = first_available_url

                self.current_announce_alerts_checked = settings.get("announce_alerts",
                                                                    FALLBACK_ANNOUNCE_ALERTS_CHECKED)
                self.current_show_log_checked = settings.get("show_log", FALLBACK_SHOW_LOG_CHECKED)
                self.current_show_alerts_area_checked = settings.get("show_alerts_area", FALLBACK_SHOW_ALERTS_AREA_CHECKED) # New
                self.current_show_forecasts_area_checked = settings.get("show_forecasts_area", FALLBACK_SHOW_FORECASTS_AREA_CHECKED) # New

                logging.info(f"Settings loaded from {settings_file}")
                self._last_valid_radar_text = self._get_display_name_for_url(self.current_radar_url) or \
                                              (list(self.RADAR_OPTIONS.keys())[0] if self.RADAR_OPTIONS else "")
            else:
                self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()
                self.current_radar_url = FALLBACK_DEFAULT_RADAR_URL
                self._last_valid_radar_text = FALLBACK_DEFAULT_RADAR_DISPLAY_NAME
                self.current_show_alerts_area_checked = FALLBACK_SHOW_ALERTS_AREA_CHECKED # New
                self.current_show_forecasts_area_checked = FALLBACK_SHOW_FORECASTS_AREA_CHECKED # New
                logging.info(f"Settings file not found. Using defaults.")

        except (json.JSONDecodeError, IOError, KeyError, IndexError) as e:
            logging.error(f"Error loading settings: {e}. Using defaults.")
            self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()
            self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
            self.current_airport_id = FALLBACK_DEFAULT_AIRPORT_ID
            self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
            self.current_radar_url = FALLBACK_DEFAULT_RADAR_URL
            self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
            self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED
            self.current_show_alerts_area_checked = FALLBACK_SHOW_ALERTS_AREA_CHECKED # New
            self.current_show_forecasts_area_checked = FALLBACK_SHOW_FORECASTS_AREA_CHECKED # New
            self._last_valid_radar_text = FALLBACK_DEFAULT_RADAR_DISPLAY_NAME

    @Slot()
    def _save_settings(self):
        resources_path = self._get_resources_path()
        if not resources_path:
            self.log_to_gui("Cannot save settings, resources path issue.", level="ERROR")
            return

        settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        settings = {
            "repeater_info": self.repeater_entry.text(),
            "airport_id": self.airport_id_entry.text(),
            "check_interval_key": self.interval_combobox.currentText(),
            "radar_options_dict": self.RADAR_OPTIONS,
            "radar_url": self.current_radar_url,
            "announce_alerts": self.announce_alerts_checkbox.isChecked(),
            "show_log": self.show_log_checkbox.isChecked(),
            "show_alerts_area": self.current_show_alerts_area_checked, # Save new state
            "show_forecasts_area": self.current_show_forecasts_area_checked # Save new state
        }
        try:
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            self.log_to_gui(f"Settings saved (Web Source URL: {self.current_radar_url})", level="INFO")
            self.update_status(f"Settings saved.")
        except (IOError, OSError) as e:
            self.log_to_gui(f"Error saving settings: {e}", level="ERROR")

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)

        top_sections_layout = QHBoxLayout()
        top_sections_layout.setSpacing(10)

        config_group = QGroupBox("Configuration")
        config_layout = QGridLayout(config_group)
        config_layout.setVerticalSpacing(10)
        config_layout.setHorizontalSpacing(5)

        row = 0
        config_layout.addWidget(QLabel("Repeater Announcement:"), row, 0,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.repeater_entry = QLineEdit(self.current_repeater_info)
        self.repeater_entry.editingFinished.connect(self._save_settings)
        config_layout.addWidget(self.repeater_entry, row, 1, 1, 2)

        row += 1
        config_layout.addWidget(QLabel("Airport ID:"), row, 0,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.airport_id_entry = QLineEdit(self.current_airport_id)
        self.airport_id_entry.setFixedWidth(100)
        self.airport_id_entry.editingFinished.connect(self._save_settings)
        self.airport_id_entry.textChanged.connect(self._update_station_forecasts_display)
        config_layout.addWidget(self.airport_id_entry, row, 1, Qt.AlignmentFlag.AlignLeft)

        airport_lookup_label = QLabel()
        airport_lookup_label.setTextFormat(Qt.TextFormat.RichText)
        airport_lookup_label.setText(
            '<a href="https://www.iata.org/en/publications/directories/code-search/">Airport ID Lookup</a>')
        airport_lookup_label.setOpenExternalLinks(True)
        config_layout.addWidget(airport_lookup_label, row, 2,
                                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        row += 1
        config_layout.addWidget(QLabel("Web Source:"), row, 0,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.radar_url_combobox = QComboBox()
        self._update_radar_combobox_items()

        initial_display_name_to_select = self._get_display_name_for_url(self.current_radar_url)
        if initial_display_name_to_select:
            self.radar_url_combobox.setCurrentText(initial_display_name_to_select)
            self._last_valid_radar_text = initial_display_name_to_select
        elif self.RADAR_OPTIONS:
            self.radar_url_combobox.setCurrentIndex(0)
            self._last_valid_radar_text = self.radar_url_combobox.currentText()
        else:
            if self.radar_url_combobox.count() > 0:
                self.radar_url_combobox.setCurrentIndex(0)
                self._last_valid_radar_text = self.radar_url_combobox.itemText(0)
            else:
                self._last_valid_radar_text = ""

        self.radar_url_combobox.currentTextChanged.connect(self._on_radar_source_selected)
        config_layout.addWidget(self.radar_url_combobox, row, 1, 1, 2)
        top_sections_layout.addWidget(config_group)

        controls_group = QGroupBox("Controls")
        controls_layout = QVBoxLayout(controls_group)
        controls_layout.setSpacing(10)

        # Visibility Toggles Layout
        visibility_toggles_layout = QHBoxLayout()
        self.show_log_checkbox = QCheckBox("Show Log")
        self.show_log_checkbox.stateChanged.connect(self._on_show_log_toggled)
        self.show_log_checkbox.stateChanged.connect(self._save_settings)
        visibility_toggles_layout.addWidget(self.show_log_checkbox)

        self.show_alerts_area_checkbox = QCheckBox("Show Alerts") # New
        self.show_alerts_area_checkbox.stateChanged.connect(self._on_show_alerts_area_toggled) # New
        self.show_alerts_area_checkbox.stateChanged.connect(self._save_settings) # New
        visibility_toggles_layout.addWidget(self.show_alerts_area_checkbox) # New

        self.show_forecasts_area_checkbox = QCheckBox("Show Forecasts") # New
        self.show_forecasts_area_checkbox.stateChanged.connect(self._on_show_forecasts_area_toggled) # New
        self.show_forecasts_area_checkbox.stateChanged.connect(self._save_settings) # New
        visibility_toggles_layout.addWidget(self.show_forecasts_area_checkbox) # New

        visibility_toggles_layout.addStretch(1)
        controls_layout.addLayout(visibility_toggles_layout)

        # Speak & Reset Button
        speak_reset_layout = QHBoxLayout()
        self.speak_reset_button = QPushButton("Speak & Reset")
        self.speak_reset_button.setToolTip("Speak Repeater Info & Reset Check Timer")
        self.speak_reset_button.clicked.connect(self._on_speak_and_reset_button_press)
        speak_reset_layout.addWidget(self.speak_reset_button)
        speak_reset_layout.addStretch(1)
        controls_layout.addLayout(speak_reset_layout)

        interval_announce_layout = QHBoxLayout()
        interval_announce_layout.addWidget(QLabel("Check Interval:"))
        self.interval_combobox = QComboBox()
        self.interval_combobox.addItems(CHECK_INTERVAL_OPTIONS.keys())
        self.interval_combobox.setCurrentText(self.current_interval_key)
        self.interval_combobox.currentTextChanged.connect(self._on_interval_selected)
        self.interval_combobox.currentTextChanged.connect(self._save_settings)
        interval_announce_layout.addWidget(self.interval_combobox)

        self.announce_alerts_checkbox = QCheckBox("Announce Alerts & Start Timer")
        self.announce_alerts_checkbox.stateChanged.connect(self._on_announce_alerts_toggled)
        self.announce_alerts_checkbox.stateChanged.connect(self._save_settings)
        interval_announce_layout.addWidget(self.announce_alerts_checkbox)
        interval_announce_layout.addStretch(1)
        controls_layout.addLayout(interval_announce_layout)

        backup_restore_layout = QHBoxLayout()
        self.backup_settings_button = QPushButton("Backup Settings")
        self.backup_settings_button.clicked.connect(self._backup_settings)
        backup_restore_layout.addWidget(self.backup_settings_button)

        self.restore_settings_button = QPushButton("Restore Settings")
        self.restore_settings_button.clicked.connect(self._restore_settings)
        backup_restore_layout.addWidget(self.restore_settings_button)
        backup_restore_layout.addStretch(1)
        controls_layout.addLayout(backup_restore_layout)

        countdown_layout = QHBoxLayout()
        countdown_layout.addStretch(1)
        self.countdown_label = QLabel("Next check in: --:--")
        font = self.countdown_label.font()
        font.setPointSize(10)
        self.countdown_label.setFont(font)
        countdown_layout.addWidget(self.countdown_label)
        controls_layout.addLayout(countdown_layout)

        controls_layout.addStretch(1)
        top_sections_layout.addWidget(controls_group)
        main_layout.addLayout(top_sections_layout)

        self.alerts_group = QGroupBox("Current Weather Alerts") # Made instance variable
        alerts_layout = QVBoxLayout(self.alerts_group)
        self.alerts_display_area = QTextEdit()
        self.alerts_display_area.setObjectName("AlertsDisplayArea")
        self.alerts_display_area.setReadOnly(True)
        self.alerts_display_area.setMinimumHeight(60)
        self.alerts_display_area.setMaximumHeight(100)
        alerts_layout.addWidget(self.alerts_display_area)
        main_layout.addWidget(self.alerts_group)

        self.combined_forecast_widget = QGroupBox("Station Forecasts") # Made instance variable
        combined_forecast_layout = QHBoxLayout(self.combined_forecast_widget)
        combined_forecast_layout.setSpacing(10)
        station_hourly_forecast_group = QWidget()
        station_hourly_forecast_layout = QVBoxLayout(station_hourly_forecast_group)
        station_hourly_forecast_layout.addWidget(QLabel("<b>4-Hour Forecast:</b>"))
        self.station_hourly_forecast_display_area = QTextEdit()
        self.station_hourly_forecast_display_area.setObjectName("StationHourlyForecastArea")
        self.station_hourly_forecast_display_area.setReadOnly(True)
        self.station_hourly_forecast_display_area.setMinimumHeight(80)
        self.station_hourly_forecast_display_area.setMaximumHeight(130)
        station_hourly_forecast_layout.addWidget(self.station_hourly_forecast_display_area)
        combined_forecast_layout.addWidget(station_hourly_forecast_group, 1)
        station_daily_forecast_group = QWidget()
        station_daily_forecast_layout = QVBoxLayout(station_daily_forecast_group)
        station_daily_forecast_layout.addWidget(QLabel("<b>3-Day Forecast:</b>"))
        self.daily_forecast_display_area = QTextEdit()
        self.daily_forecast_display_area.setObjectName("DailyForecastArea")
        self.daily_forecast_display_area.setReadOnly(True)
        self.daily_forecast_display_area.setMinimumHeight(80)
        self.daily_forecast_display_area.setMaximumHeight(130)
        station_daily_forecast_layout.addWidget(self.daily_forecast_display_area)
        combined_forecast_layout.addWidget(station_daily_forecast_group, 1)
        main_layout.addWidget(self.combined_forecast_widget)

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
            if self.web_view:
                self.splitter.setStretchFactor(self.splitter.indexOf(self.web_view), 0)

        main_layout.addWidget(self.splitter, 1)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.update_status("Application started. Configure and check 'Announce Alerts' to begin.")
        self._reload_radar_view()

    def _apply_loaded_settings_to_ui(self):
        """Updates UI elements to reflect currently loaded settings."""
        self.repeater_entry.setText(self.current_repeater_info)
        self.airport_id_entry.setText(self.current_airport_id)
        self.interval_combobox.setCurrentText(self.current_interval_key)

        self._update_radar_combobox_items()
        current_radar_display_name = self._get_display_name_for_url(self.current_radar_url)
        if current_radar_display_name:
            self.radar_url_combobox.setCurrentText(current_radar_display_name)
        elif self.RADAR_OPTIONS:
            self.radar_url_combobox.setCurrentIndex(0)
            self.current_radar_url = self.RADAR_OPTIONS.get(self.radar_url_combobox.currentText(), "")

        self.announce_alerts_checkbox.setChecked(self.current_announce_alerts_checked)
        self.show_log_checkbox.setChecked(self.current_show_log_checked)
        self.log_area.setVisible(self.current_show_log_checked)

        # Apply new checkbox states and visibility
        self.show_alerts_area_checkbox.setChecked(self.current_show_alerts_area_checked)
        if hasattr(self, 'alerts_group'):
            self.alerts_group.setVisible(self.current_show_alerts_area_checked)

        self.show_forecasts_area_checkbox.setChecked(self.current_show_forecasts_area_checked)
        if hasattr(self, 'combined_forecast_widget'):
            self.combined_forecast_widget.setVisible(self.current_show_forecasts_area_checked)


        self._on_announce_alerts_toggled(self.announce_alerts_checkbox.checkState().value)
        self._reload_radar_view()
        self.log_to_gui("Settings applied to UI.", level="INFO")

    @Slot()
    def _backup_settings(self):
        resources_path = self._get_resources_path()
        if not resources_path:
            QMessageBox.critical(self, "Error", "Resource directory not found. Cannot backup settings.")
            return
        current_settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        if not os.path.exists(current_settings_file):
            QMessageBox.information(self, "Backup Settings", "No settings file found to backup.")
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        suggested_filename = f"weather_app_settings_backup_{timestamp}.txt"
        fileName, _ = QFileDialog.getSaveFileName(self, "Backup Settings File", suggested_filename,
                                                  "Text Files (*.txt);;All Files (*)")
        if fileName:
            try:
                shutil.copy(current_settings_file, fileName)
                QMessageBox.information(self, "Backup Successful", f"Settings backed up to:\n{fileName}")
                self.log_to_gui(f"Settings backed up to {fileName}", level="INFO")
            except Exception as e:
                QMessageBox.critical(self, "Backup Failed", f"Could not backup settings: {e}")
                self.log_to_gui(f"Failed to backup settings to {fileName}: {e}", level="ERROR")

    @Slot()
    def _restore_settings(self):
        fileName, _ = QFileDialog.getOpenFileName(self, "Restore Settings File", "",
                                                  "Text Files (*.txt);;All Files (*)")
        if fileName:
            resources_path = self._get_resources_path()
            if not resources_path:
                QMessageBox.critical(self, "Error", "Resource directory not found. Cannot restore settings.")
                return
            current_settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)

            try:
                shutil.copy(fileName, current_settings_file)
                self.log_to_gui(f"Settings restored from {fileName}. Reloading...", level="INFO")
                self._load_settings()
                self._apply_loaded_settings_to_ui()
                QMessageBox.information(self, "Restore Successful",
                                        f"Settings restored from:\n{fileName}\nApplication UI updated.")
            except Exception as e:
                QMessageBox.critical(self, "Restore Failed", f"Could not restore settings: {e}")
                self.log_to_gui(f"Failed to restore settings from {fileName}: {e}", level="ERROR")

    def _update_radar_combobox_items(self):
        self.radar_url_combobox.blockSignals(True)
        text_to_restore = self._last_valid_radar_text
        if self.radar_url_combobox.count() > 0:
            current_cb_text = self.radar_url_combobox.currentText()
            if current_cb_text and current_cb_text not in [ADD_NEW_SOURCE_TEXT, MANAGE_SOURCES_TEXT, ADD_CURRENT_SOURCE_TEXT]:
                text_to_restore = current_cb_text

        self.radar_url_combobox.clear()
        for name in self.RADAR_OPTIONS.keys():
            self.radar_url_combobox.addItem(name)
        self.radar_url_combobox.addItem(ADD_NEW_SOURCE_TEXT)
        self.radar_url_combobox.addItem(ADD_CURRENT_SOURCE_TEXT)
        self.radar_url_combobox.addItem(MANAGE_SOURCES_TEXT)


        if text_to_restore in self.RADAR_OPTIONS:
            self.radar_url_combobox.setCurrentText(text_to_restore)
        elif self.RADAR_OPTIONS:
            self.radar_url_combobox.setCurrentIndex(0)
            self._last_valid_radar_text = self.radar_url_combobox.currentText()
        else: # No actual sources, only special items might be left
            if self.radar_url_combobox.count() > 0:
                self.radar_url_combobox.setCurrentIndex(0) # Select the first special item
                self._last_valid_radar_text = self.radar_url_combobox.itemText(0)
            else:
                self._last_valid_radar_text = ""
        self.radar_url_combobox.blockSignals(False)

    def _get_display_name_for_url(self, url_to_find):
        for name, url_val in self.RADAR_OPTIONS.items():
            if url_val == url_to_find:
                return name
        return None

    @Slot(QUrl)
    def _on_webview_url_changed(self, new_qurl):
        if not QWebEngineView or not self.web_view or not isinstance(self.web_view, QWebEngineView):
            return
        new_url_str = new_qurl.toString()
        if new_url_str == self.current_radar_url or new_url_str == "about:blank":
            return

        self.log_to_gui(f"Web Source URL changed in WebView to: {new_url_str}", level="DEBUG")
        self.current_radar_url = new_url_str
        display_name_for_new_url = self._get_display_name_for_url(new_url_str)
        if display_name_for_new_url:
            if self.radar_url_combobox.currentText() != display_name_for_new_url:
                self.radar_url_combobox.blockSignals(True)
                self.radar_url_combobox.setCurrentText(display_name_for_new_url)
                self._last_valid_radar_text = display_name_for_new_url
                self.radar_url_combobox.blockSignals(False)
        self._save_settings()

    @Slot(str)
    def _on_radar_source_selected(self, selected_display_name):
        if not selected_display_name:
            return

        if selected_display_name == ADD_NEW_SOURCE_TEXT:
            dialog = AddEditSourceDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                name, url = dialog.get_data()
                if name and url:
                    if name in [ADD_NEW_SOURCE_TEXT, MANAGE_SOURCES_TEXT, ADD_CURRENT_SOURCE_TEXT] or name in self.RADAR_OPTIONS:
                        QMessageBox.warning(self, "Invalid Name", f"The name '{name}' is reserved or already exists.")
                        self.radar_url_combobox.setCurrentText(self._last_valid_radar_text)
                        return
                    self.RADAR_OPTIONS[name] = url
                    self._update_radar_combobox_items()
                    self.radar_url_combobox.setCurrentText(name)
                else:
                    QMessageBox.warning(self, "Invalid Input", "Both name and a valid URL are required.")
                    self.radar_url_combobox.setCurrentText(self._last_valid_radar_text)
            else:
                self.radar_url_combobox.setCurrentText(self._last_valid_radar_text)

        elif selected_display_name == ADD_CURRENT_SOURCE_TEXT:
            current_url_in_view = self.current_radar_url
            if not current_url_in_view or current_url_in_view == "about:blank":
                QMessageBox.warning(self, "No Current URL", "No valid URL is currently loaded in the web view.")
                self.radar_url_combobox.setCurrentText(self._last_valid_radar_text)
                return

            existing_name = self._get_display_name_for_url(current_url_in_view)
            if existing_name:
                QMessageBox.information(self, "URL Already Saved",
                                        f"This URL ({current_url_in_view}) is already saved as '{existing_name}'.")
                self.radar_url_combobox.setCurrentText(existing_name)
                return

            name_dialog = GetNameDialog(self, url_to_save=current_url_in_view)
            if name_dialog.exec() == QDialog.DialogCode.Accepted:
                name = name_dialog.get_name()
                if name:
                    if name in [ADD_NEW_SOURCE_TEXT, MANAGE_SOURCES_TEXT, ADD_CURRENT_SOURCE_TEXT] or name in self.RADAR_OPTIONS:
                        QMessageBox.warning(self, "Invalid Name", f"The name '{name}' is reserved or already exists.")
                        self.radar_url_combobox.setCurrentText(self._last_valid_radar_text)
                        return
                    self.RADAR_OPTIONS[name] = current_url_in_view
                    self._update_radar_combobox_items()
                    self.radar_url_combobox.setCurrentText(name)
                else:
                    QMessageBox.warning(self, "Invalid Input", "A name is required to save the current source.")
                    self.radar_url_combobox.setCurrentText(self._last_valid_radar_text)
            else:
                self.radar_url_combobox.setCurrentText(self._last_valid_radar_text)


        elif selected_display_name == MANAGE_SOURCES_TEXT:
            dialog = ManageSourcesDialog(self.RADAR_OPTIONS.copy(), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                updated_sources = dialog.get_sources()
                # Always update if OK was pressed, as order is significant
                self.RADAR_OPTIONS = updated_sources
                self._update_radar_combobox_items()

                current_display_name_for_url = self._get_display_name_for_url(self.current_radar_url)

                if current_display_name_for_url and current_display_name_for_url in self.RADAR_OPTIONS:
                    if self.radar_url_combobox.currentText() != current_display_name_for_url:
                        self.radar_url_combobox.setCurrentText(current_display_name_for_url)
                elif self.RADAR_OPTIONS:
                    self.log_to_gui("Previously selected web source no longer exists or URL changed. Selecting first available.", level="INFO")
                    first_name = list(self.RADAR_OPTIONS.keys())[0]
                    self.radar_url_combobox.setCurrentText(first_name)
                else:
                    self.log_to_gui("All web sources deleted.", level="WARNING")
                    self.current_radar_url = ""
                    if hasattr(self, 'web_view') and QWebEngineView and isinstance(self.web_view, QWebEngineView):
                        self.web_view.setUrl(QUrl("about:blank"))
                    self._last_valid_radar_text = ""
                self._save_settings()
            else: # Dialog was cancelled
                self.log_to_gui("Manage sources dialog cancelled.", level="DEBUG")
                if self._last_valid_radar_text in self.RADAR_OPTIONS:
                     self.radar_url_combobox.setCurrentText(self._last_valid_radar_text)
                elif self.RADAR_OPTIONS:
                     self.radar_url_combobox.setCurrentText(list(self.RADAR_OPTIONS.keys())[0])

        else:  # Regular source selected
            self._last_valid_radar_text = selected_display_name
            new_url = self.RADAR_OPTIONS.get(selected_display_name)
            if new_url:
                if new_url != self.current_radar_url:
                    self.current_radar_url = new_url
                    self.log_to_gui(f"Web Source: {selected_display_name} ({self.current_radar_url})", level="INFO")
                    self._reload_radar_view()
                self._save_settings()
            else:
                self.log_to_gui(f"Selected web source '{selected_display_name}' not found.", level="WARNING")
                if self._last_valid_radar_text in self.RADAR_OPTIONS:
                    self.radar_url_combobox.setCurrentText(self._last_valid_radar_text)
                elif self.RADAR_OPTIONS:
                    self.radar_url_combobox.setCurrentIndex(0)

    def _reload_radar_view(self):
        if not self.current_radar_url:
            self.log_to_gui("Current Web Source URL is empty.", level="WARNING")
            if hasattr(self, 'web_view') and QWebEngineView and isinstance(self.web_view, QWebEngineView):
                self.web_view.setUrl(QUrl("about:blank"))
            return

        if self.current_radar_url.lower().endswith(".pdf"):
            self.log_to_gui(f"Opening PDF externally: {self.current_radar_url}", level="INFO")
            if hasattr(self, 'web_view') and QWebEngineView and isinstance(self.web_view, QWebEngineView):
                self.web_view.setHtml(
                    "<div style='display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; text-align:center; padding:20px; font-family:sans-serif;'>"
                    "<h3>PDF Document</h3>"
                    "<p>This link points to a PDF document, which will be opened in your system's default PDF viewer or web browser.</p>"
                    f"<p><a href='{self.current_radar_url}'>If it doesn't open, click here: {self.current_radar_url}</a></p>"
                    "</div>"
                )
            opened = QDesktopServices.openUrl(QUrl(self.current_radar_url))
            if not opened:
                self.log_to_gui(f"Could not automatically open PDF: {self.current_radar_url}", level="ERROR")
                QMessageBox.warning(self, "Open PDF Failed",
                                    f"Could not automatically open the PDF. Please try opening the link manually:\n{self.current_radar_url}")
            return

        if QWebEngineView and hasattr(self, 'web_view') and isinstance(self.web_view, QWebEngineView):
            if self.web_view.url().toString() != self.current_radar_url:
                self.log_to_gui(f"Loading web content: {self.current_radar_url}", level="DEBUG")
                self.web_view.setUrl(QUrl(self.current_radar_url))
        elif not QWebEngineView:
            self.log_to_gui("Web view component (QWebEngineView) is not available to display this content.",
                            level="WARNING")

    def _initialize_tts_engine(self):
        try:
            engine = pyttsx3.init()
            if engine is None: raise RuntimeError("pyttsx3.init() returned None")
            return engine
        except Exception as e:
            logging.error(f"TTS engine init failed: {e}.")
            return self._DummyEngine()

    class _DummyEngine:
        def say(self, text, name=None): logging.info(f"TTS (Fallback): {text}")
        def runAndWait(self): pass
        def stop(self): pass
        def isBusy(self): return False
        def getProperty(self, name): return None
        def setProperty(self, name, value): pass

    def log_to_gui(self, message, level="INFO"):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}"
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.log_area.setTextCursor(cursor)
        self.log_area.insertPlainText(formatted_message + "\n")
        if level == "ERROR":
            logging.error(message)
        elif level == "WARNING":
            logging.warning(message)
        elif level == "DEBUG":
            logging.debug(message)
        else:
            logging.info(message)

    def update_status(self, message):
        self.status_bar.showMessage(message)

    def _format_time(self, total_seconds):
        if total_seconds < 0: total_seconds = 0
        minutes, seconds = divmod(int(total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0: return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @Slot()
    def _update_countdown_display(self):
        if self.remaining_time_seconds > 0: self.remaining_time_seconds -= 1
        if not self.announce_alerts_checkbox.isChecked() and self.remaining_time_seconds <= 0:
            self.countdown_label.setText("Next check in: --:-- (Paused)")
        else:
            self.countdown_label.setText(f"Next check in: {self._format_time(self.remaining_time_seconds)}")

    def _reset_and_start_countdown(self, total_seconds_for_interval):
        self.countdown_timer.stop()
        self.remaining_time_seconds = total_seconds_for_interval
        self.countdown_label.setText(f"Next check in: {self._format_time(self.remaining_time_seconds)}")
        if total_seconds_for_interval > 0 and self.announce_alerts_checkbox.isChecked():
            self.countdown_timer.start(1000)
        elif not self.announce_alerts_checkbox.isChecked():
            self.countdown_label.setText("Next check in: --:-- (Paused)")

    @Slot(int)
    def _on_show_log_toggled(self, state):
        is_checked = (state == Qt.CheckState.Checked.value)
        self.log_area.setVisible(is_checked)
        self.log_to_gui(f"Log display {'en' if is_checked else 'dis'}abled.", level="DEBUG")

    @Slot(int)
    def _on_show_alerts_area_toggled(self, state):
        is_checked = (state == Qt.CheckState.Checked.value)
        if hasattr(self, 'alerts_group'):
            self.alerts_group.setVisible(is_checked)
        self.current_show_alerts_area_checked = is_checked
        self.log_to_gui(f"Current Weather Alerts display {'en' if is_checked else 'dis'}abled.", level="DEBUG")

    @Slot(int)
    def _on_show_forecasts_area_toggled(self, state):
        is_checked = (state == Qt.CheckState.Checked.value)
        if hasattr(self, 'combined_forecast_widget'):
            self.combined_forecast_widget.setVisible(is_checked)
        self.current_show_forecasts_area_checked = is_checked
        self.log_to_gui(f"Station Forecasts display {'en' if is_checked else 'dis'}abled.", level="DEBUG")


    @Slot(int)
    def _on_announce_alerts_toggled(self, state):
        is_checked = (state == Qt.CheckState.Checked.value)
        if is_checked:
            self.log_to_gui("Alert announcements enabled.", level="INFO")
            self.update_status("Alerts enabled. Starting check cycle...")
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(100, self.perform_check_cycle)
        else:
            self.log_to_gui("Alert announcements disabled.", level="INFO")
            self.update_status("Alerts disabled. Timer paused.")
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            self.countdown_label.setText("Next check in: --:-- (Paused)")

    @Slot(str)
    def _on_interval_selected(self, selected_key):
        new_interval_ms = CHECK_INTERVAL_OPTIONS.get(selected_key)
        if new_interval_ms is None or new_interval_ms == self.current_check_interval_ms:
            if new_interval_ms is None: self.log_to_gui(f"Invalid interval: {selected_key}.", level="WARNING")
            return
        self.current_check_interval_ms = new_interval_ms
        self.log_to_gui(f"Interval: {selected_key} ({self.current_check_interval_ms // 60000}m).", level="INFO")
        if self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.stop()
            self.log_to_gui(f"Restarting check cycle.", level="DEBUG")
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(100, self.perform_check_cycle)
            self.update_status(f"Interval: {selected_key}. Next check ~{self.current_check_interval_ms // 60000}m.")
        else:
            self.update_status(f"Interval: {selected_key}. Announcements paused.")

    def _fetch_station_coordinates(self, airport_id_input, log_errors=True):
        if not airport_id_input:
            if log_errors: self.log_to_gui("Airport ID empty.", level="ERROR")
            return None
        nws_station_id = "K" + airport_id_input.upper()
        station_url = NWS_STATION_API_URL_TEMPLATE.format(station_id=nws_station_id)
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (your.email@example.com)',
                   'Accept': 'application/geo+json'}
        self.log_to_gui(f"Fetching coords for {nws_station_id} from {station_url}", level="DEBUG")
        try:
            response = requests.get(station_url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            geometry = data.get('geometry')
            if geometry and geometry.get('type') == 'Point':
                coords = geometry.get('coordinates')
                if coords and len(coords) == 2:
                    self.log_to_gui(f"Coords for {nws_station_id}: Lat={coords[1]}, Lon={coords[0]}", level="INFO")
                    return coords[1], coords[0]
            if log_errors: self.log_to_gui(f"Could not parse coords for {nws_station_id}.", level="ERROR")
            return None
        except requests.exceptions.HTTPError as e:
            if log_errors:
                self.log_to_gui(f"HTTP error for {nws_station_id}: {e}", level="ERROR")
                status_msg = f"Error: NWS Station 'K{airport_id_input}' not found." if e.response and e.response.status_code == 404 else f"Error: NWS data for 'K{airport_id_input}'."
                self.update_status(status_msg)
            return None
        except requests.exceptions.RequestException as e:
            if log_errors: self.log_to_gui(f"Network error for {nws_station_id}: {e}", level="ERROR")
            self.update_status(f"Error: Network issue for station data.")
            return None
        except ValueError:
            if log_errors: self.log_to_gui(f"Invalid JSON for {nws_station_id}.", level="ERROR")
            self.update_status(f"Error: Invalid NWS station data.")
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
            response = requests.get(points_url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if log_errors: self.log_to_gui(f"Error fetching gridpoint: {e}", level="ERROR")
            return None
        except ValueError:
            if log_errors: self.log_to_gui(f"Invalid JSON from gridpoint.", level="ERROR")
            return None

    def _fetch_forecast_data_from_url(self, forecast_url, log_errors=True):
        if not forecast_url: return None
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (your.email@example.com)',
                   'Accept': 'application/geo+json'}
        self.log_to_gui(f"Fetching forecast: {forecast_url}", level="DEBUG")
        try:
            response = requests.get(forecast_url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if log_errors: self.log_to_gui(f"Error fetching forecast from {forecast_url}: {e}", level="ERROR")
            return None
        except ValueError:
            if log_errors: self.log_to_gui(f"Invalid JSON for forecast from {forecast_url}.", level="ERROR")
            return None

    def _format_station_hourly_forecast_display(self, forecast_json):
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            return "4-Hour forecast data unavailable."
        periods = forecast_json['properties']['periods']
        display_text = [
            f"{p.get('startTime', '').split('T')[1].split(':')[0:2][0]}:{p.get('startTime', '').split('T')[1].split(':')[0:2][1]}: {p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}, {p.get('shortForecast', 'N/A')}"
            for i, p in enumerate(periods) if i < 4]
        return "\n".join(display_text) if display_text else "No 4-hour forecast periods found."

    def _format_daily_forecast_display(self, forecast_json):
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            return "3-Day forecast data unavailable."
        periods = forecast_json['properties']['periods']
        display_text = []
        for p in periods[:6]:
            name = p.get('name', 'N/A')
            temp_label = "High" if "High" in name or p.get("isDaytime", False) else "Low"
            temp = f"{p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}"
            short_fc = p.get('shortForecast', 'N/A')
            display_text.append(f"{name.replace(' Night', ' Nt')}: {temp_label} {temp}, {short_fc}")
        return "\n".join(display_text) if display_text else "No 3-day forecast periods found."

    def _update_station_forecasts_display(self):
        airport_id = self.airport_id_entry.text().strip()
        if not airport_id:
            self.station_hourly_forecast_display_area.setText("Airport ID empty.")
            self.daily_forecast_display_area.setText("Airport ID empty.")
            return

        self.station_hourly_forecast_display_area.setText(f"Fetching 4hr forecast for K{airport_id}...")
        self.daily_forecast_display_area.setText(f"Fetching 3-day forecast for K{airport_id}...")
        QApplication.processEvents()

        coords = self._fetch_station_coordinates(airport_id, log_errors=False)
        if not coords:
            msg = f"Could not get coords for K{airport_id}."
            self.station_hourly_forecast_display_area.setText(msg)
            self.daily_forecast_display_area.setText(msg)
            return

        lat, lon = coords
        grid_props = self._fetch_gridpoint_properties(lat, lon)
        if not grid_props or 'properties' not in grid_props:
            msg = f"Could not get forecast URLs for K{airport_id}."
            self.station_hourly_forecast_display_area.setText(msg)
            self.daily_forecast_display_area.setText(msg)
            return

        props = grid_props['properties']
        hourly_url = props.get('forecastHourly')
        if hourly_url:
            hourly_json = self._fetch_forecast_data_from_url(hourly_url)
            self.station_hourly_forecast_display_area.setText(
                self._format_station_hourly_forecast_display(hourly_json) if hourly_json
                else f"Could not get 4hr forecast for K{airport_id}.")
        else:
            self.station_hourly_forecast_display_area.setText(f"4hr forecast URL not found for K{airport_id}.")

        daily_url = props.get('forecast')
        if daily_url:
            daily_json = self._fetch_forecast_data_from_url(daily_url)
            self.daily_forecast_display_area.setText(
                self._format_daily_forecast_display(daily_json) if daily_json
                else f"Could not get 3-day forecast for K{airport_id}.")
        else:
            self.daily_forecast_display_area.setText(f"3-day forecast URL not found for K{airport_id}.")

    def _get_current_weather_url(self, log_errors=True):
        airport_id = self.airport_id_entry.text().strip()
        if not airport_id:
            if log_errors: self.log_to_gui("Airport ID empty for alert URL.", level="ERROR")
            self.update_status("Error: Airport ID empty.")
            return None
        coords = self._fetch_station_coordinates(airport_id, log_errors=log_errors)
        if coords:
            return f"{WEATHER_URL_PREFIX}{coords[0]}%2C{coords[1]}{WEATHER_URL_SUFFIX}"
        if log_errors: self.log_to_gui(f"Failed to get coords for K{airport_id} (alerts).", level="ERROR")
        return None

    def _get_alerts(self, url):
        if not url: return []
        self.log_to_gui(f"Fetching alerts: {url}", level="DEBUG")
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (your.email@example.com)'}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            self.log_to_gui(f"Fetched {len(feed.entries)} entries.", level="DEBUG")
            return feed.entries
        except requests.exceptions.Timeout:
            self.log_to_gui(f"Timeout fetching alerts.", level="ERROR")
        except requests.exceptions.HTTPError as e:
            self.log_to_gui(f"HTTP error for alerts: {e}", level="ERROR")
        except requests.exceptions.RequestException as e:
            self.log_to_gui(f"Error fetching alerts: {e}", level="ERROR")
        return []

    def _update_alerts_display_area(self, alerts):
        self.alerts_display_area.clear()
        airport_id = self.airport_id_entry.text().strip()
        loc_name = f"K{airport_id}" if airport_id else "selected location"
        if not alerts:
            self.alerts_display_area.setText(f"No active alerts for {loc_name}.")
            return
        html_lines = [
            f"<strong style='color:{'red' if 'warning' in a.get('title', '').lower() else 'orange' if 'watch' in a.get('title', '').lower() else 'blue' if 'advisory' in a.get('title', '').lower() else 'black'};'>{a.get('title', 'N/A')}</strong>"
            for a in alerts]
        self.alerts_display_area.setHtml("<br>".join(html_lines))

    def _speak_message_internal(self, text_to_speak, log_prefix="Spoken"):
        if not text_to_speak: return
        try:
            self.tts_engine.say(text_to_speak)
            self.tts_engine.runAndWait()
            self.log_to_gui(f"{log_prefix}: {text_to_speak}", level="INFO")
        except Exception as e:
            self.log_to_gui(f"TTS error for '{text_to_speak}': {e}", level="ERROR")

    def _speak_weather_alert(self, alert_title, alert_summary):
        msg = f"Weather Alert: {alert_title}. Details: {alert_summary}"
        if self.repeater_entry.text(): msg += f". {self.repeater_entry.text()}"
        self._speak_message_internal(msg, log_prefix="Spoken Alert")

    def _speak_repeater_info(self):
        if self.repeater_entry.text():
            self._speak_message_internal(self.repeater_entry.text())

    @Slot()
    def _on_speak_and_reset_button_press(self):
        self.log_to_gui("Speak & Reset pressed.", level="INFO")
        self._speak_repeater_info()
        if self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.stop()
            self.log_to_gui(f"Resetting timer.", level="DEBUG")
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(100, self.perform_check_cycle)
            self.update_status(f"Manual reset. Next check ~{self.current_check_interval_ms // 60000}m.")
        else:
            self.update_status("Repeater info spoken. Alerts paused.")

    @Slot()
    def perform_check_cycle(self):
        if not self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.stop();
            self.countdown_timer.stop()
            self.countdown_label.setText("Next check in: --:-- (Paused)")
            self.log_to_gui("Alerts disabled. Skipping check.", level="DEBUG")
            return

        self.main_check_timer.stop()
        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
        self._reload_radar_view()
        self._update_station_forecasts_display()

        airport_id = self.airport_id_entry.text().strip()
        self.log_to_gui(f"Checking K{airport_id}...", level="INFO")
        self.update_status(f"Checking K{airport_id}... Last: {time.strftime('%H:%M:%S')}")

        alert_url = self._get_current_weather_url()
        alerts = self._get_alerts(alert_url) if alert_url else []
        self._update_alerts_display_area(alerts)

        new_alerts_found = False
        for alert in alerts:
            if not all(hasattr(alert, attr) for attr in ['id', 'title', 'summary']):
                self.log_to_gui(f"Malformed alert: {alert}", level="WARNING");
                continue
            if alert.id not in self.seen_alert_ids:
                new_alerts_found = True
                self.log_to_gui(f"New Alert: {alert.title}", level="IMPORTANT")
                if self.announce_alerts_checkbox.isChecked():
                    self._speak_weather_alert(alert.title, alert.summary)
                self.seen_alert_ids.add(alert.id)

        if not new_alerts_found and alert_url and alerts:
            self.log_to_gui(f"No new alerts. Active: {len(alerts)}. Seen: {len(self.seen_alert_ids)}.", level="INFO")
        elif not alerts and alert_url:
            self.log_to_gui(f"No active alerts for K{airport_id}.", level="INFO")

        if self.announce_alerts_checkbox.isChecked(): self._speak_repeater_info()
        self.update_status(f"Check complete. Next in ~{self.current_check_interval_ms // 60000}m.")
        self.log_to_gui(f"Waiting {self.current_check_interval_ms // 1000}s.", level="INFO")
        if self.current_check_interval_ms > 0 and self.announce_alerts_checkbox.isChecked():
            self.main_check_timer.start(self.current_check_interval_ms)

    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Quit', "Quit Weather Alert Monitor?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log_to_gui("Shutting down...", level="INFO")
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
    if "Fusion" in QStyleFactory.keys(): app.setStyle(QStyleFactory.create("Fusion"))

    qss_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), RESOURCES_FOLDER_NAME,
                                 STYLESHEET_FILE_NAME)
    qss_file = QFile(qss_file_path)
    if qss_file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
        app.setStyleSheet(QTextStream(qss_file).readAll())
        qss_file.close()
        logging.info(f"Applied stylesheet: {STYLESHEET_FILE_NAME}")
    else:
        logging.warning(f"Stylesheet not found: {qss_file_path}. Error: {qss_file.errorString()}")

    main_win = WeatherAlertApp()
    main_win.show()
    sys.exit(app.exec())