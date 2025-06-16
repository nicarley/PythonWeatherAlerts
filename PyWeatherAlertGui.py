import sys  # System-specific parameters and functions
import requests  # For making HTTP requests to fetch weather data
import feedparser  # For parsing ATOM feeds (used for NWS alerts)
import pyttsx3  # For text-to-speech functionality
import time  # For time-related functions (formatting, delays)
import logging  # For logging application events
import os  # For interacting with the operating system (paths, file operations)
import json  # For working with JSON data (settings)
import shutil  # For high-level file operations (copying)

# PySide6 imports for GUI elements
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QMessageBox,
    QStatusBar, QCheckBox, QSplitter, QStyleFactory, QGroupBox, QDialog,
    QDialogButtonBox, QFormLayout, QListWidget, QListWidgetItem,
    QSpacerItem, QSizePolicy, QFileDialog, QFrame
)
from PySide6.QtCore import Qt, QTimer, Slot, QUrl, QFile, \
    QTextStream  # Core Qt functionalities (signals, slots, timers, URLs)
from PySide6.QtGui import (
    QTextCursor, QIcon, QColor, QDesktopServices, QPalette, QAction,
    QActionGroup  # GUI-related classes (icons, colors, actions)
)

# Attempt to import QWebEngineView for displaying web content
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None  # Set to None if not available
    logging.warning("PySide6.QtWebEngineWidgets not found. Web view will be disabled.")

# --- Application Version ---
# Sets the version number to the current date in YY.MM.DD format.
versionnumber = "25.06.16"  # Set version to current date in YY.MM.DD format.

# --- Constants ---
# Fallback values for application settings if not found in the settings file.
FALLBACK_INITIAL_CHECK_INTERVAL_MS = 900 * 1000  # Default check interval: 15 minutes (in milliseconds)
FALLBACK_DEFAULT_INTERVAL_KEY = "15 Minutes"  # Default display key for the check interval
FALLBACK_DEFAULT_LOCATION_ID = "SLO"  # Default location ID (e.g., KSLE -> SLE, or a zip code)
FALLBACK_INITIAL_REPEATER_INFO = ""  # Default repeater announcement string
GITHUB_HELP_URL = "https://github.com/nicarley/PythonWeatherAlerts#pyweatheralertgui---weather-alert-monitor"  # URL for help documentation

# Default options for web sources (e.g., radar sites)
DEFAULT_RADAR_OPTIONS = {
    "N.W.S. Radar": "https://radar.weather.gov/",
    "Windy.com": "https://www.windy.com/"
}
FALLBACK_DEFAULT_RADAR_DISPLAY_NAME = "N.W.S. Radar"  # Default display name for the radar source
FALLBACK_DEFAULT_RADAR_URL = DEFAULT_RADAR_OPTIONS[
    FALLBACK_DEFAULT_RADAR_DISPLAY_NAME]  # Default URL for the radar source

# Fallback values for UI checkbox states
FALLBACK_ANNOUNCE_ALERTS_CHECKED = False
FALLBACK_SHOW_LOG_CHECKED = False
FALLBACK_SHOW_ALERTS_AREA_CHECKED = True
FALLBACK_SHOW_FORECASTS_AREA_CHECKED = True
FALLBACK_AUTO_REFRESH_CONTENT_CHECKED = False
FALLBACK_DARK_MODE_ENABLED = False

# Available options for the weather check interval, mapping display names to milliseconds
CHECK_INTERVAL_OPTIONS = {
    "1 Minute": 1 * 60 * 1000, "5 Minutes": 5 * 60 * 1000,
    "10 Minutes": 10 * 60 * 1000, "15 Minutes": 15 * 60 * 1000,
    "30 Minutes": 30 * 60 * 1000, "1 Hour": 60 * 60 * 1000,
}

# NWS API URL templates
NWS_STATION_API_URL_TEMPLATE = "https://api.weather.gov/stations/{station_id}"  # For station details (like coordinates)
NWS_POINTS_API_URL_TEMPLATE = "https://api.weather.gov/points/{latitude},{longitude}"  # For gridpoint data (forecast URLs)
WEATHER_URL_PREFIX = "https://api.weather.gov/alerts/active.atom?point="  # Base URL for NWS alerts ATOM feed
# WEATHER_URL_SUFFIX = "&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Future%2CExpected"  # Filters for alert feed

# File and folder names
SETTINGS_FILE_NAME = "settings.txt"  # Name of the settings file
RESOURCES_FOLDER_NAME = "resources"  # Name of the folder for resources (icons, stylesheets)
LIGHT_STYLESHEET_FILE_NAME = "modern.qss"  # Stylesheet for light mode
DARK_STYLESHEET_FILE_NAME = "dark_modern.qss"  # Stylesheet for dark mode

# Text constants for menu items related to web sources
ADD_NEW_SOURCE_TEXT = "Add New Source..."
MANAGE_SOURCES_TEXT = "Manage Sources..."
ADD_CURRENT_SOURCE_TEXT = "Add Current View as Source..."

# --- Logging Configuration ---
# Sets up basic logging: INFO level, with a timestamp, level name, and message.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Dialog Classes ---

class AboutDialog(QDialog):
    """
    A dialog to display information about the application.
    """
    def __init__(self, parent=None):
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

        # Ok button
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setLayout(layout)


class AddEditSourceDialog(QDialog):
    """
    A dialog for adding a new web source or editing an existing one.
    It prompts the user for a display name and a URL.
    """

    def __init__(self, parent=None, current_name=None, current_url=None):
        """
        Initializes the dialog.
        Args:
            parent: The parent widget.
            current_name (str, optional): The current name if editing.
            current_url (str, optional): The current URL if editing.
        """
        super().__init__(parent)
        if current_name and current_url:
            self.setWindowTitle("Edit Web Source")  # Set title for editing
        else:
            self.setWindowTitle("Add New Web Source")  # Set title for adding
        self.layout = QFormLayout(self)  # Use a form layout for neat rows

        # Input field for the display name
        self.name_edit = QLineEdit(self)
        # Input field for the URL
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("https://example.com/radar_or_page.html")  # Placeholder text for URL format

        # Pre-fill fields if editing
        if current_name: self.name_edit.setText(current_name)
        if current_url: self.url_edit.setText(current_url)

        # Add rows to the form layout
        self.layout.addRow("Display Name:", self.name_edit)
        self.layout.addRow("URL (Web Page or PDF):", self.url_edit)

        # Standard OK and Cancel buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        Qt.Orientation.Horizontal, self)
        self.buttons.accepted.connect(self.accept)  # Connect OK to accept
        self.buttons.rejected.connect(self.reject)  # Connect Cancel to reject
        self.layout.addWidget(self.buttons)

    def get_data(self):
        """
        Retrieves the entered name and URL from the dialog.
        Returns:
            tuple: (name, url) if valid, otherwise (None, None).
                   Validates that name and URL are not empty and URL starts with http/https.
        """
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        # Basic validation for name and URL
        if name and url and (url.startswith("http://") or url.startswith("https://")):
            return name, url
        return None, None


class GetNameDialog(QDialog):
    """
    A dialog to get a display name for a given URL, typically used when saving
    the currently viewed web page as a new source.
    """

    def __init__(self, parent=None, url_to_save=""):
        """
        Initializes the dialog.
        Args:
            parent: The parent widget.
            url_to_save (str): The URL for which a name is being requested.
        """
        super().__init__(parent)
        self.setWindowTitle("Name This Source")
        self.layout = QFormLayout(self)

        # Input field for the display name
        self.name_edit = QLineEdit(self)
        # Label to display the URL being saved
        self.url_label = QLabel(f"URL: {url_to_save}")
        self.url_label.setWordWrap(True)  # Allow URL to wrap if too long

        self.layout.addRow("Display Name:", self.name_edit)
        self.layout.addRow(self.url_label)

        # Standard OK and Cancel buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        Qt.Orientation.Horizontal, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)
        self.name_edit.setFocus()  # Set focus to the name input field

    def get_name(self):
        """
        Retrieves the entered name from the dialog.
        Returns:
            str: The entered name, or None if empty.
        """
        name = self.name_edit.text().strip()
        return name if name else None


class ManageSourcesDialog(QDialog):
    """
    A dialog for managing the list of web sources (e.g., radar sites).
    Allows users to reorder, edit, and delete sources.
    """

    def __init__(self, radar_options_dict, parent=None):
        """
        Initializes the dialog.
        Args:
            radar_options_dict (dict): The current dictionary of radar options {name: url}.
            parent: The parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Manage Web Sources")
        self.setGeometry(200, 200, 500, 350)  # Set dialog size and position
        self.layout = QVBoxLayout(self)

        # List widget to display sources
        self.list_widget = QListWidget(self)
        self.list_widget.setAlternatingRowColors(True)  # Improves readability
        self.populate_list(radar_options_dict)  # Fill the list with current sources
        self.layout.addWidget(self.list_widget)

        # Layout for action buttons (Move Up, Move Down, Edit, Delete)
        self.button_layout = QHBoxLayout()
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        self.edit_button = QPushButton("Edit")
        self.delete_button = QPushButton("Delete")

        # Connect button clicks to their respective methods
        self.up_button.clicked.connect(self.move_item_up)
        self.down_button.clicked.connect(self.move_item_down)
        self.edit_button.clicked.connect(self.edit_item)
        self.delete_button.clicked.connect(self.delete_item)

        # Add buttons to the layout
        self.button_layout.addWidget(self.up_button)
        self.button_layout.addWidget(self.down_button)
        self.button_layout.addWidget(self.edit_button)
        self.button_layout.addStretch(1)  # Add stretch to push delete button to the right
        self.button_layout.addWidget(self.delete_button)
        self.layout.addLayout(self.button_layout)

        # Standard OK and Cancel buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        Qt.Orientation.Horizontal, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

        # Connect list widget signals to update button states or trigger actions
        self.list_widget.currentRowChanged.connect(
            self.update_button_state)  # Enable/disable buttons based on selection
        self.list_widget.itemDoubleClicked.connect(self.edit_item)  # Allow editing on double-click
        self.update_button_state(self.list_widget.currentRow())  # Initial button state

    def populate_list(self, radar_options_dict):
        """
        Populates the list widget with items from the radar_options_dict.
        Each item displays the name and URL, and stores the name/URL pair as data.
        Args:
            radar_options_dict (dict): Dictionary of {name: url} for web sources.
        """
        self.list_widget.clear()  # Clear existing items
        for name, url in radar_options_dict.items():
            item = QListWidgetItem(f"{name}  ({url})")  # Display text for the item
            # Store the original name and URL with the item for later retrieval
            item.setData(Qt.ItemDataRole.UserRole, {"name": name, "url": url})
            self.list_widget.addItem(item)

    def update_button_state(self, current_row):
        """
        Enables or disables the action buttons based on the current selection in the list.
        Args:
            current_row (int): The index of the currently selected row.
        """
        has_selection = current_row >= 0
        self.delete_button.setEnabled(has_selection)
        self.edit_button.setEnabled(has_selection)
        # "Move Up" is enabled if an item is selected and it's not the first item
        self.up_button.setEnabled(has_selection and current_row > 0)
        # "Move Down" is enabled if an item is selected and it's not the last item
        self.down_button.setEnabled(has_selection and current_row < self.list_widget.count() - 1)

    def move_item_up(self):
        """Moves the selected item one position up in the list."""
        row = self.list_widget.currentRow()
        if row > 0:  # Can only move up if not the first item
            item = self.list_widget.takeItem(row)  # Remove item
            self.list_widget.insertItem(row - 1, item)  # Insert at new position
            self.list_widget.setCurrentRow(row - 1)  # Keep the moved item selected

    def move_item_down(self):
        """Moves the selected item one position down in the list."""
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:  # Can only move down if not the last item
            item = self.list_widget.takeItem(row)  # Remove item
            self.list_widget.insertItem(row + 1, item)  # Insert at new position
            self.list_widget.setCurrentRow(row + 1)  # Keep the moved item selected

    def edit_item(self):
        """Opens the AddEditSourceDialog to edit the selected web source."""
        item = self.list_widget.currentItem()
        if not item: return  # Do nothing if no item is selected

        data = item.data(Qt.ItemDataRole.UserRole)  # Get stored name and URL
        dialog = AddEditSourceDialog(self, data.get("name"), data.get("url"))
        if dialog.exec() == QDialog.DialogCode.Accepted:  # If user clicks OK
            name, url = dialog.get_data()
            if name and url:
                # Check for name conflicts (excluding the item being edited)
                for i in range(self.list_widget.count()):
                    loop_item = self.list_widget.item(i)
                    if loop_item == item: continue  # Skip self
                    if loop_item.data(Qt.ItemDataRole.UserRole).get("name") == name:
                        QMessageBox.warning(self, "Name Conflict", f"The name '{name}' is already in use.")
                        return
                # Update the item's display text and stored data
                item.setText(f"{name}  ({url})")
                item.setData(Qt.ItemDataRole.UserRole, {"name": name, "url": url})
            else:
                QMessageBox.warning(self, "Invalid Input", "Both name and URL are required.")

    def delete_item(self):
        """Deletes the selected item from the list after confirmation."""
        row = self.list_widget.currentRow()
        if row >= 0:  # If an item is selected
            name_to_delete = self.list_widget.item(row).data(Qt.ItemDataRole.UserRole).get("name", "this source")
            # Ask for confirmation before deleting
            if QMessageBox.question(self, 'Delete Source', f"Delete '{name_to_delete}'?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.list_widget.takeItem(row)  # Remove the item

    def get_sources(self):
        """
        Returns the current list of web sources as a dictionary.
        Returns:
            dict: A dictionary of {name: url} representing the sources in their current order.
        """
        # Reconstruct the dictionary from the items in the list widget
        return {self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)["name"]:
                    self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)["url"] for i in
                range(self.list_widget.count())}


class SettingsDialog(QDialog):
    """
    A dialog for configuring application preferences such as repeater info,
    location ID (zip/airport), and check interval.
    """

    def __init__(self, parent=None, current_settings=None):
        """
        Initializes the dialog.
        Args:
            parent: The parent widget.
            current_settings (dict, optional): Dictionary of current settings to pre-fill the dialog.
        """
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.current_settings = current_settings if current_settings else {}

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()  # Use a form layout for settings

        # Input for repeater announcement text
        self.repeater_entry = QLineEdit(self.current_settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO))
        form_layout.addRow("Repeater Announcement:", self.repeater_entry)

        # Input for Location ID (e.g., SLE for KSLE, or 90210)
        self.location_id_entry = QLineEdit(self.current_settings.get("location_id", FALLBACK_DEFAULT_LOCATION_ID))
        self.location_id_entry.setFixedWidth(150)  # Adjust width for zip or airport ID
        location_id_layout = QHBoxLayout()  # Layout for ID entry and lookup link
        location_id_layout.addWidget(self.location_id_entry)

        # Airport ID lookup link (kept for now, user can ignore if entering zip)
        airport_lookup_label = QLabel()
        airport_lookup_label.setTextFormat(Qt.TextFormat.RichText)
        airport_lookup_label.setText(
            '<a href="https://www.iata.org/en/publications/directories/code-search/">Airport ID Lookup (IATA)</a>')
        airport_lookup_label.setOpenExternalLinks(True)
        location_id_layout.addWidget(airport_lookup_label)
        location_id_layout.addStretch()
        form_layout.addRow("Location (US Zip/Airport ID):", location_id_layout)

        # Combobox for selecting the check interval
        self.interval_combobox = QComboBox()
        self.interval_combobox.addItems(CHECK_INTERVAL_OPTIONS.keys())  # Populate with defined intervals
        self.interval_combobox.setCurrentText(self.current_settings.get("interval_key", FALLBACK_DEFAULT_INTERVAL_KEY))
        form_layout.addRow("Check Interval:", self.interval_combobox)

        layout.addLayout(form_layout)

        # Standard OK and Cancel buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def get_settings_data(self):
        """
        Retrieves the configured settings from the dialog.
        Returns:
            dict: A dictionary containing the new "repeater_info", "location_id", and "interval_key".
        """
        return {
            "repeater_info": self.repeater_entry.text(),
            "location_id": self.location_id_entry.text().strip().upper(),  # Store location ID as uppercase and stripped
            "interval_key": self.interval_combobox.currentText()
        }


class WeatherAlertApp(QMainWindow):
    """
    The main application window for the Weather Alert Monitor.
    Handles UI, settings, fetching weather data, and announcements.
    """

    def __init__(self):
        """Initializes the main application window."""
        super().__init__()
        self.setWindowTitle(f"Weather Alert Monitor Version {versionnumber}")  # Set window title with version
        self.setGeometry(100, 100, 850, 780)  # Set initial window size and position

        # Initialize application state variables with defaults or copies of defaults
        self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()  # Mutable copy of radar options
        self._last_valid_radar_text = FALLBACK_DEFAULT_RADAR_DISPLAY_NAME  # Tracks the last selected valid radar source
        self.current_radar_url = FALLBACK_DEFAULT_RADAR_URL  # Currently selected radar URL

        # Initialize current settings with fallback values
        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.current_location_id = FALLBACK_DEFAULT_LOCATION_ID  # Changed from airport_id
        self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
        self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
        self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED
        self.current_show_alerts_area_checked = FALLBACK_SHOW_ALERTS_AREA_CHECKED
        self.current_show_forecasts_area_checked = FALLBACK_SHOW_FORECASTS_AREA_CHECKED
        self.current_auto_refresh_content_checked = FALLBACK_AUTO_REFRESH_CONTENT_CHECKED
        self.current_dark_mode_enabled = FALLBACK_DARK_MODE_ENABLED

        self._load_settings()  # Load settings from file or use defaults
        self._set_window_icon()  # Set the application icon

        self.seen_alert_ids = set()  # Stores IDs of alerts already announced to avoid repetition
        self.tts_engine = self._initialize_tts_engine()  # Initialize Text-To-Speech engine
        self.is_tts_dummy = isinstance(self.tts_engine, self._DummyEngine)  # Flag if TTS is a dummy (failed init)

        # Calculate current check interval in milliseconds
        self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
            self.current_interval_key, FALLBACK_INITIAL_CHECK_INTERVAL_MS)

        # Timer for periodic weather checks
        self.main_check_timer = QTimer(self)
        self.main_check_timer.timeout.connect(self.perform_check_cycle)
        # Timer for updating the countdown display
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_countdown_display)
        self.remaining_time_seconds = 0  # Seconds remaining until the next check

        # Timer for updating the current time display (initialized later in _init_ui)
        self.clock_timer = None
        self.current_time_label = None

        self._init_ui()  # Initialize the user interface elements
        self._apply_loaded_settings_to_ui()  # Apply loaded settings to UI components

        # Log TTS engine status
        if self.is_tts_dummy:
            self.log_to_gui("TTS engine failed. Using fallback.", level="ERROR")
        else:
            self.log_to_gui("TTS engine initialized.", level="INFO")

        # Log initial monitoring status
        self.log_to_gui(f"Monitoring Location: {self.current_location_id}", level="INFO")  # Changed
        initial_radar_display_name_log = self._get_display_name_for_url(self.current_radar_url) or \
                                         (list(self.RADAR_OPTIONS.keys())[0] if self.RADAR_OPTIONS else "None")
        self.log_to_gui(f"Initial Web Source: {initial_radar_display_name_log} ({self.current_radar_url})",
                        level="INFO")

        # Initial data fetches and UI updates
        self._update_station_forecasts_display()  # Fetch and display initial forecasts
        self._update_alerts_display_area([])  # Clear or show initial alert status
        self._update_main_timer_state()  # Start or pause timers based on settings

    def _set_window_icon(self):
        """Sets the application window icon, trying PNG then ICO format."""
        base_path = os.path.dirname(os.path.abspath(__file__))  # Get directory of the script
        icon_path_png = os.path.join(base_path, RESOURCES_FOLDER_NAME, "icon.png")
        icon_path_ico = os.path.join(base_path, RESOURCES_FOLDER_NAME, "icon.ico")
        app_icon = QIcon()
        if os.path.exists(icon_path_png):
            app_icon.addFile(icon_path_png)
        elif os.path.exists(icon_path_ico):  # Fallback to ICO if PNG not found
            app_icon.addFile(icon_path_ico)

        if not app_icon.isNull():  # If icon was loaded successfully
            self.setWindowIcon(app_icon)
        else:
            logging.warning(f"Could not load app icon from {icon_path_png} or {icon_path_ico}.")

    def _get_resources_path(self):
        """
        Gets the absolute path to the resources directory.
        Creates the directory if it doesn't exist.
        Returns:
            str: The path to the resources directory, or None if creation fails.
        """
        base_path = os.path.dirname(os.path.abspath(__file__))  # Get script's directory
        resources_path = os.path.join(base_path, RESOURCES_FOLDER_NAME)
        if not os.path.exists(resources_path):
            try:
                os.makedirs(resources_path)  # Create directory if it doesn't exist
                logging.info(f"Created resources directory: {resources_path}")
            except OSError as e:
                logging.error(f"Could not create resources dir {resources_path}: {e}")
                return None  # Return None on failure
        return resources_path

    def _load_settings(self):
        """
        Loads application settings from the settings file.
        If the file doesn't exist or is corrupt, uses fallback default values.
        """
        resources_path = self._get_resources_path()
        if not resources_path:
            logging.error("Cannot load settings, resources path issue.")
            self._apply_fallback_settings("Resources path unavailable.")
            return

        settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        settings_loaded_successfully = False
        try:
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    settings = json.load(f)

                self.current_repeater_info = settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO)
                self.current_location_id = settings.get("location_id", FALLBACK_DEFAULT_LOCATION_ID)  # Changed
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
            logging.error(f"Error loading settings from {settings_file}: {e}. Using defaults.")

        if not settings_loaded_successfully:
            log_message = f"Settings file '{settings_file}' not found or invalid. Using defaults."
            if os.path.exists(settings_file):
                log_message = f"Settings file '{settings_file}' was invalid. Using defaults."
            self._apply_fallback_settings(log_message)

    def _apply_fallback_settings(self, reason_message):
        """Applies all fallback settings and logs the reason."""
        logging.info(reason_message)
        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.current_location_id = FALLBACK_DEFAULT_LOCATION_ID  # Changed
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

    @Slot()
    def _save_settings(self):
        """Saves the current application settings to the settings file."""
        resources_path = self._get_resources_path()
        if not resources_path:
            self.log_to_gui("Cannot save settings, resources path issue.", level="ERROR")
            return

        settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        settings = {
            "repeater_info": self.current_repeater_info,
            "location_id": self.current_location_id,  # Changed
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
            self.log_to_gui(f"Error saving settings to {settings_file}: {e}", level="ERROR")

    def _init_ui(self):
        """Initializes all user interface elements of the main window."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)

        self.top_status_widget = QWidget()
        top_status_layout = QHBoxLayout(self.top_status_widget)
        top_status_layout.setContentsMargins(5, 3, 5, 3)

        self.top_repeater_label = QLabel("Repeater: N/A")
        self.top_location_label = QLabel("Location: N/A")  # Changed from top_airport_label
        self.top_interval_label = QLabel("Interval: N/A")
        self.top_countdown_label = QLabel("Next Check: --:--")
        self.current_time_label = QLabel("Time: --:--:--")  # New label for current time

        top_status_layout.addWidget(self.top_repeater_label)
        top_status_layout.addSpacing(20)
        top_status_layout.addWidget(self.top_location_label)  # Changed
        top_status_layout.addSpacing(20)
        top_status_layout.addWidget(self.top_interval_label)
        top_status_layout.addStretch(1)
        top_status_layout.addWidget(self.top_countdown_label)
        top_status_layout.addSpacing(15)  # Spacing before current time
        top_status_layout.addWidget(self.current_time_label)  # Add current time label

        self.top_status_widget.setObjectName("TopStatusBar")
        main_layout.addWidget(self.top_status_widget)

        # Timer for updating the current time display
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_current_time_display)
        self.clock_timer.start(1000)  # Update every second
        self._update_current_time_display()  # Initial call to set time

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

        # Add Full Screen toggle action
        self.toggle_fullscreen_action = QAction("Toggle &Full Screen", self)
        self.toggle_fullscreen_action.setShortcut("F11")
        self.toggle_fullscreen_action.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(self.toggle_fullscreen_action)

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

        help_menu = menu_bar.addMenu("&Help")
        github_help_action = QAction("View Help on GitHub", self)
        github_help_action.triggered.connect(self._show_github_help)
        help_menu.addAction(github_help_action)
        help_menu.addSeparator() # Add separator before About
        about_action = QAction("&About Weather Alert Monitor...", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)


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
        station_hourly_forecast_layout.addWidget(QLabel("<b>8-Hour Forecast:</b>")) # Changed
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
        station_daily_forecast_layout.addWidget(QLabel("<b>5-Day Forecast:</b>")) # Changed
        self.daily_forecast_display_area = QTextEdit()
        self.daily_forecast_display_area.setObjectName("DailyForecastArea")
        self.daily_forecast_display_area.setReadOnly(True)
        self.daily_forecast_display_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        station_daily_forecast_layout.addWidget(self.daily_forecast_display_area)
        combined_forecast_layout.addWidget(station_daily_forecast_group, 1)

        alerts_forecasts_layout.addWidget(self.combined_forecast_widget, 2)
        main_layout.addLayout(alerts_forecasts_layout)

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
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.update_status("Application started.")
        self._reload_radar_view()

    @Slot()
    def _update_current_time_display(self):
        """Updates the current time label in the top status bar."""
        current_time_str = time.strftime("%I:%M:%S %p")  # e.g., 03:45:20 PM
        if hasattr(self, 'current_time_label') and self.current_time_label:
            self.current_time_label.setText(f"Time: {current_time_str}")

    @Slot()
    def _toggle_fullscreen(self):
        """Toggles the main window's full-screen state."""
        if self.isFullScreen():
            self.showNormal()
            self.log_to_gui("Exited full screen mode.", level="INFO")
        else:
            self.showFullScreen()
            self.log_to_gui("Entered full screen mode (Press F11 to exit).", level="INFO")

    @Slot()
    def _show_about_dialog(self):
        """Shows the About dialog."""
        dialog = AboutDialog(self)
        dialog.exec()

    def _update_top_status_bar_display(self):
        """Updates the labels in the top status bar with current preference values."""
        if hasattr(self, 'top_repeater_label'):
            repeater_text = self.current_repeater_info if self.current_repeater_info else "N/A"
            max_len = 30
            if len(repeater_text) > max_len:
                repeater_text = repeater_text[:max_len - 3] + "..."
            self.top_repeater_label.setText(f"Repeater: {repeater_text}")
            self.top_repeater_label.setToolTip(self.current_repeater_info if self.current_repeater_info else "Not set")

            self.top_location_label.setText(
                f"Location: {self.current_location_id if self.current_location_id else 'N/A'}")  # Changed
            self.top_interval_label.setText(f"Interval: {self.current_interval_key}")

    def _apply_loaded_settings_to_ui(self):
        """Updates UI elements (menu actions, visibility) to reflect currently loaded settings."""
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
        """Opens the SettingsDialog to allow users to change preferences."""
        current_prefs = {
            "repeater_info": self.current_repeater_info,
            "location_id": self.current_location_id,  # Changed
            "interval_key": self.current_interval_key
        }
        dialog = SettingsDialog(self, current_settings=current_prefs)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_settings_data()

            self.current_repeater_info = new_data["repeater_info"]
            location_changed = self.current_location_id != new_data["location_id"]  # Changed
            self.current_location_id = new_data["location_id"]  # Changed
            interval_changed = self.current_interval_key != new_data["interval_key"]
            self.current_interval_key = new_data["interval_key"]

            self._update_top_status_bar_display()

            if location_changed:  # Changed
                self.log_to_gui(
                    f"Location ID changed to: {self.current_location_id}", level="INFO")  # Changed
                self._update_station_forecasts_display()
                self.seen_alert_ids.clear()

                self.log_to_gui(f"Location ID changed, refreshing alerts display for {self.current_location_id}.",
                                level="DEBUG")  # Changed
                if hasattr(self, 'alerts_display_area'):
                    self.alerts_display_area.setText(f"Fetching alerts for {self.current_location_id}...")  # Changed
                    QApplication.processEvents()

                alert_url = self._get_current_weather_url()
                alerts = self._get_alerts(alert_url) if alert_url else []
                self._update_alerts_display_area(alerts)

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
        """
        Handles the toggling of the dark mode action.
        Applies the new color scheme and saves the setting.
        Args:
            checked (bool): True if dark mode is enabled, False otherwise.
        """
        if checked != self.current_dark_mode_enabled:
            self.log_to_gui(f"Dark Mode {'enabled' if checked else 'disabled'}.", level="INFO")
            self.current_dark_mode_enabled = checked
            self._apply_color_scheme()
            self._save_settings()

    def _apply_color_scheme(self):
        """Applies the appropriate stylesheet (light or dark) to the application."""
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
        if not resources_path:
            self.log_to_gui("Cannot apply stylesheet, resources path issue.", level="ERROR")
            return

        qss_file_path = os.path.join(resources_path, qss_file_to_load)
        qss_file = QFile(qss_file_path)
        if qss_file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
            app.setStyleSheet(QTextStream(qss_file).readAll())
            qss_file.close()
            self.log_to_gui(f"Applied stylesheet: {qss_file_to_load}", level="INFO")
        else:
            self.log_to_gui(
                f"Stylesheet {qss_file_to_load} not found or could not be opened: {qss_file_path}. Error: {qss_file.errorString()}",
                level="WARNING")

    @Slot()
    def _show_github_help(self):
        """Opens the GitHub help page in the user's default external web browser."""
        self.log_to_gui(f"Opening GitHub help page in external browser: {GITHUB_HELP_URL}", level="INFO")
        opened = QDesktopServices.openUrl(QUrl(GITHUB_HELP_URL))
        if not opened:
            self.log_to_gui(f"Could not automatically open GitHub help URL: {GITHUB_HELP_URL}", level="ERROR")
            QMessageBox.warning(self, "Open URL Failed",
                                f"Could not automatically open the help page. Please try opening the link manually in your browser:\n{GITHUB_HELP_URL}")

    @Slot()
    def _backup_settings(self):
        """Allows the user to save a backup copy of the current settings file."""
        resources_path = self._get_resources_path()
        if not resources_path:
            QMessageBox.critical(self, "Error", "Resource directory not found. Cannot backup settings.")
            return
        current_settings_file = os.path.join(resources_path, SETTINGS_FILE_NAME)
        if not os.path.exists(current_settings_file):
            QMessageBox.information(self, "Backup Settings", "No settings file to backup.")
            return

        suggested_filename = f"weather_app_settings_backup_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        fileName, _ = QFileDialog.getSaveFileName(self, "Backup Settings File",
                                                  suggested_filename,
                                                  "Text Files (*.txt);;All Files (*)")
        if fileName:
            try:
                shutil.copy(current_settings_file, fileName)
                QMessageBox.information(self, "Backup Successful",
                                        f"Settings backed up to:\n{fileName}")
                self.log_to_gui(f"Settings backed up to {fileName}", level="INFO")
            except Exception as e:
                QMessageBox.critical(self, "Backup Failed", f"Could not backup settings: {e}")
                self.log_to_gui(f"Failed to backup settings to {fileName}: {e}", level="ERROR")

    @Slot()
    def _restore_settings(self):
        """Allows the user to restore settings from a previously backed-up file."""
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
                self._apply_color_scheme()
                self._update_station_forecasts_display()
                self.seen_alert_ids.clear()
                self._update_main_timer_state()
                QMessageBox.information(self, "Restore Successful",
                                        f"Settings restored from:\n{fileName}\nApplication UI updated.")
            except Exception as e:
                QMessageBox.critical(self, "Restore Failed", f"Could not restore settings: {e}")
                self.log_to_gui(f"Failed to restore settings from {fileName}: {e}", level="ERROR")

    def _update_web_sources_menu(self):
        """Rebuilds the 'Web Sources' submenu based on the current RADAR_OPTIONS."""
        if not hasattr(self, 'web_sources_menu'): return

        self.web_sources_menu.clear()
        self.web_source_action_group = QActionGroup(self)
        self.web_source_action_group.setExclusive(True)

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
        """
        Finds the display name associated with a given URL in RADAR_OPTIONS.
        Args:
            url_to_find (str): The URL to search for.
        Returns:
            str: The display name if found, otherwise None.
        """
        for name, url_val in self.RADAR_OPTIONS.items():
            if url_val == url_to_find:
                return name
        return None

    @Slot(QUrl)
    def _on_webview_url_changed(self, new_qurl):
        """
        Slot connected to the web_view's urlChanged signal.
        Updates the current_radar_url if the user navigates within the web_view,
        and attempts to update the selected item in the Web Sources menu.
        Args:
            new_qurl (QUrl): The new URL loaded in the web_view.
        """
        if not QWebEngineView or not self.web_view or not isinstance(self.web_view, QWebEngineView):
            return

        new_url_str = new_qurl.toString()
        if new_url_str == self.current_radar_url or new_url_str == "about:blank" or new_url_str == GITHUB_HELP_URL:
            return

        self.log_to_gui(f"Web Source URL changed in WebView to: {new_url_str}", level="DEBUG")
        self.current_radar_url = new_url_str

        display_name_for_new_url = self._get_display_name_for_url(new_url_str)
        if display_name_for_new_url:
            for action in self.web_source_action_group.actions():
                if action.data() == display_name_for_new_url:
                    if not action.isChecked():
                        action.setChecked(True)
                    self._last_valid_radar_text = display_name_for_new_url
                    break
        self._save_settings()

    @Slot(str)
    def _on_radar_source_selected(self, selected_text_data):
        """
        Handles selection of items from the 'Web Sources' menu.
        Args:
            selected_text_data (str): The text/data of the selected QAction.
        """
        if not selected_text_data: return

        if selected_text_data == ADD_NEW_SOURCE_TEXT:
            dialog = AddEditSourceDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                name, url = dialog.get_data()
                if name and url:
                    if name in [ADD_NEW_SOURCE_TEXT, MANAGE_SOURCES_TEXT,
                                ADD_CURRENT_SOURCE_TEXT] or name in self.RADAR_OPTIONS:
                        QMessageBox.warning(self, "Invalid Name", f"The name '{name}' is reserved or already exists.")
                        self._recheck_last_valid_source_in_menu()
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
            self._recheck_last_valid_source_in_menu()

        elif selected_text_data == ADD_CURRENT_SOURCE_TEXT:
            current_url_in_view = ""
            if QWebEngineView and self.web_view and isinstance(self.web_view, QWebEngineView):
                current_url_in_view = self.web_view.url().toString()

            if not current_url_in_view or current_url_in_view == "about:blank" or current_url_in_view == GITHUB_HELP_URL:
                QMessageBox.warning(self, "No Savable URL", "No valid user-navigated URL is currently loaded to save.")
                self._recheck_last_valid_source_in_menu()
                return

            existing_name = self._get_display_name_for_url(current_url_in_view)
            if existing_name:
                QMessageBox.information(self, "URL Already Saved",
                                        f"This URL ({current_url_in_view}) is already saved as '{existing_name}'.")
                self._recheck_last_valid_source_in_menu(existing_name)
                return

            name_dialog = GetNameDialog(self, url_to_save=current_url_in_view)
            if name_dialog.exec() == QDialog.DialogCode.Accepted:
                name = name_dialog.get_name()
                if name:
                    if name in [ADD_NEW_SOURCE_TEXT, MANAGE_SOURCES_TEXT,
                                ADD_CURRENT_SOURCE_TEXT] or name in self.RADAR_OPTIONS:
                        QMessageBox.warning(self, "Invalid Name", f"The name '{name}' is reserved or already exists.")
                        self._recheck_last_valid_source_in_menu()
                        return
                    self.RADAR_OPTIONS[name] = current_url_in_view
                    self._update_web_sources_menu()
                    for action in self.web_source_action_group.actions():
                        if action.data() == name: action.setChecked(True); break
                    self.current_radar_url = current_url_in_view
                    self._last_valid_radar_text = name
                    self._save_settings()
                else:
                    QMessageBox.warning(self, "Invalid Input", "A name is required.")
            self._recheck_last_valid_source_in_menu()

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
                    self._recheck_last_valid_source_in_menu(first_available_name)
                elif not self.RADAR_OPTIONS:
                    self.current_radar_url = ""
                    self._last_valid_radar_text = ""
                    if hasattr(self, 'web_view') and QWebEngineView and isinstance(self.web_view, QWebEngineView):
                        self.web_view.setUrl(QUrl("about:blank"))
                self._save_settings()
            self._recheck_last_valid_source_in_menu()

        else:
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
                self._recheck_last_valid_source_in_menu()

    def _recheck_last_valid_source_in_menu(self, specific_name_to_check=None):
        """Ensures the menu's checked state matches _last_valid_radar_text or a specific name."""
        name_to_ensure_checked = specific_name_to_check if specific_name_to_check else self._last_valid_radar_text
        if name_to_ensure_checked and name_to_ensure_checked in self.RADAR_OPTIONS:
            for action in self.web_source_action_group.actions():
                if action.data() == name_to_ensure_checked:
                    if not action.isChecked(): action.setChecked(True)
                    return
        elif self.RADAR_OPTIONS:
            first_name = list(self.RADAR_OPTIONS.keys())[0]
            for action in self.web_source_action_group.actions():
                if action.data() == first_name:
                    if not action.isChecked(): action.setChecked(True)
                    return

    def _reload_radar_view(self):
        """
        Reloads the content in the web_view based on current_radar_url.
        """
        if not self.current_radar_url:
            self.log_to_gui("Current Web Source URL is empty. Loading blank page.", level="WARNING")
            if hasattr(self, 'web_view') and QWebEngineView and isinstance(self.web_view, QWebEngineView):
                self.web_view.setUrl(QUrl("about:blank"))
            return

        if self.current_radar_url.lower().endswith(".pdf"):
            self.log_to_gui(f"Opening PDF externally: {self.current_radar_url}", level="INFO")
            if hasattr(self, 'web_view') and QWebEngineView and isinstance(self.web_view, QWebEngineView):
                self.web_view.setHtml(
                    f"<div style='text-align:center; padding:20px;'><h3>PDF Document</h3><p>Attempting to open PDF externally: <a href='{self.current_radar_url}'>{self.current_radar_url}</a></p><p>If it doesn't open, please check your system's PDF viewer association.</p></div>")
            if not QDesktopServices.openUrl(QUrl(self.current_radar_url)):
                self.log_to_gui(f"Could not automatically open PDF: {self.current_radar_url}", level="ERROR")
                QMessageBox.warning(self, "Open PDF Failed",
                                    f"Could not automatically open the PDF. Please try opening the link manually:\n{self.current_radar_url}")
            return

        if QWebEngineView and hasattr(self, 'web_view') and isinstance(self.web_view, QWebEngineView):
            current_view_url = self.web_view.url().toString()
            target_url = self.current_radar_url

            if target_url == "about:blank" or target_url == GITHUB_HELP_URL:
                if current_view_url != target_url:
                    self.log_to_gui(f"Loading special page: {target_url}", level="DEBUG")
                    self.web_view.setUrl(QUrl(target_url))
                return

            if self.auto_refresh_action.isChecked():
                if current_view_url == target_url:
                    self.log_to_gui(f"Auto-refreshing web content: {target_url}", level="DEBUG")
                    self.web_view.reload()
                else:
                    self.log_to_gui(f"Auto-refresh: Loading web content: {target_url}", level="DEBUG")
                    self.web_view.setUrl(QUrl(target_url))
            else:
                if current_view_url != target_url:
                    self.log_to_gui(f"Loading web content (auto-refresh off): {target_url}", level="DEBUG")
                    self.web_view.setUrl(QUrl(target_url))
        elif not QWebEngineView:
            self.log_to_gui("WebEngineView not available. Cannot display web content.", level="WARNING")

    def _initialize_tts_engine(self):
        """
        Initializes the pyttsx3 text-to-speech engine.
        """
        try:
            engine = pyttsx3.init()
            return engine if engine else self._DummyEngine()
        except Exception as e:
            logging.error(f"TTS engine initialization failed: {e}. Using fallback.")
            return self._DummyEngine()

    class _DummyEngine:
        """A fallback TTS engine that logs messages instead of speaking them."""

        def say(self, text, name=None):
            logging.info(f"TTS (Fallback/Dummy): {text}")

        def runAndWait(self): pass

        def stop(self): pass

        def isBusy(self): return False

        def getProperty(self, name): return None

        def setProperty(self, name, value): pass

    def log_to_gui(self, message, level="INFO"):
        """
        Logs a message to both the GUI log area and the standard Python logger.
        """
        formatted_message = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level.upper()}] {message}"
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.log_area.setTextCursor(cursor)
        self.log_area.insertPlainText(formatted_message + "\n")

        getattr(logging, level.lower(), logging.info)(message)

    def update_status(self, message):
        """Updates the message in the bottom status bar."""
        self.status_bar.showMessage(message)

    def _format_time(self, total_seconds):
        """
        Formats a duration in seconds into HH:MM:SS or MM:SS string.
        """
        if total_seconds < 0: total_seconds = 0
        minutes, seconds = divmod(int(total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    @Slot()
    def _update_countdown_display(self):
        """
        Called by countdown_timer every second to update the remaining time display.
        """
        if self.remaining_time_seconds > 0:
            self.remaining_time_seconds -= 1

        status_text = ""
        if not (self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()) and \
                self.remaining_time_seconds <= 0:
            status_text = "Next Check: --:-- (Paused)"
        else:
            status_text = f"Next Check: {self._format_time(self.remaining_time_seconds)}"

        if hasattr(self, 'top_countdown_label'):
            self.top_countdown_label.setText(status_text)

    def _reset_and_start_countdown(self, total_seconds_for_interval):
        """
        Resets the countdown timer with a new interval and starts it.
        """
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
            if self.remaining_time_seconds > 0 and not is_active:
                self.remaining_time_seconds = 0

        if hasattr(self, 'top_countdown_label'):
            self.top_countdown_label.setText(status_text)
        self._update_countdown_display()

    @Slot(bool)
    def _on_show_log_toggled(self, checked):
        """Handles toggling the visibility of the log panel."""
        self.log_area.setVisible(checked)
        self.current_show_log_checked = checked
        self.log_to_gui(f"Log display panel {'en' if checked else 'dis'}abled.", level="DEBUG")
        self._save_settings()

    @Slot(bool)
    def _on_show_alerts_area_toggled(self, checked):
        """Handles toggling the visibility of the current alerts area."""
        if hasattr(self, 'alerts_group'): self.alerts_group.setVisible(checked)
        self.current_show_alerts_area_checked = checked
        self.log_to_gui(f"Current Alerts display area {'en' if checked else 'dis'}abled.", level="DEBUG")
        self._save_settings()

    @Slot(bool)
    def _on_show_forecasts_area_toggled(self, checked):
        """Handles toggling the visibility of the station forecasts area."""
        if hasattr(self, 'combined_forecast_widget'): self.combined_forecast_widget.setVisible(checked)
        self.current_show_forecasts_area_checked = checked
        self.log_to_gui(f"Station Forecasts display area {'en' if checked else 'dis'}abled.", level="DEBUG")
        self._save_settings()

    def _update_main_timer_state(self):
        """
        Updates the state of the main_check_timer and countdown.
        """
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
            self.log_to_gui("All timed activities disabled. Timed checks paused.", level="INFO")
            self.update_status("Timed checks paused.")
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            if hasattr(self, 'top_countdown_label'):
                self.top_countdown_label.setText("Next Check: --:-- (Paused)")

    @Slot(bool)
    def _on_announce_alerts_toggled(self, checked):
        """Handles toggling the 'Announce Alerts' action."""
        self.current_announce_alerts_checked = checked
        self.log_to_gui(f"Alert announcements {'enabled' if checked else 'disabled'}.", level="INFO")
        self._update_main_timer_state()
        self._save_settings()

    @Slot(bool)
    def _on_auto_refresh_content_toggled(self, checked):
        """Handles toggling the 'Auto-Refresh Content' action."""
        self.current_auto_refresh_content_checked = checked
        self.log_to_gui(f"Auto-refresh web content {'enabled' if checked else 'disabled'}.", level="INFO")
        self._update_main_timer_state()
        if checked and self.main_check_timer.isActive():
            self._reload_radar_view()
        self._save_settings()

    def _geocode_zip_to_coordinates(self, zip_code, country='us'):
        """
        Converts a US zip code to latitude and longitude using pgeocode.
        (Requires pgeocode and pandas to be installed)
        Args:
            zip_code (str): The 5-digit US zip code.
            country (str): The country code (default 'us').
        Returns:
            tuple: (latitude, longitude) if successful, otherwise None.
        """
        try:
            import pgeocode
            import pandas as pd
        except ImportError:
            self.log_to_gui("pgeocode or pandas library not found. Zip code lookup cannot proceed.", level="ERROR")
            self.update_status("Error: pgeocode/pandas missing for zip code.")
            return None

        if not zip_code or not zip_code.isdigit() or len(zip_code) != 5:
            self.log_to_gui(f"Invalid zip code format for geocoding: {zip_code}", level="ERROR")
            return None
        try:
            nomi = pgeocode.Nominatim(country)
            location_info = nomi.query_postal_code(zip_code)

            if location_info.empty or pd.isna(location_info.latitude) or pd.isna(location_info.longitude):
                self.log_to_gui(f"Could not find coordinates for zip code: {zip_code} in country {country}.",
                                level="WARNING")
                return None
            lat = location_info.latitude
            lon = location_info.longitude
            self.log_to_gui(f"Coordinates for zip code {zip_code}: Lat={lat}, Lon={lon}", level="INFO")
            return lat, lon
        except Exception as e:
            self.log_to_gui(f"Error geocoding zip code {zip_code}: {e}", level="ERROR")
            return None

    def _fetch_station_coordinates(self, full_nws_station_id, log_errors=True):
        """
        Fetches geographic coordinates (latitude, longitude) for a given FULL NWS station ID
        from the NWS API.
        Args:
            full_nws_station_id (str): The full NWS station ID (e.g., "KSLE", "PANC").
            log_errors (bool): Whether to log errors to GUI/console.
        Returns:
            tuple: (latitude, longitude) if successful, otherwise None.
        """
        if not full_nws_station_id:
            if log_errors: self.log_to_gui("NWS Station ID for coordinate lookup is empty.", level="ERROR")
            return None

        station_url = NWS_STATION_API_URL_TEMPLATE.format(station_id=full_nws_station_id)
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (github.com/nicarley/PythonWeatherAlerts)',
                   'Accept': 'application/geo+json'}
        if log_errors: self.log_to_gui(
            f"Fetching coordinates for NWS Station ID '{full_nws_station_id}' from {station_url}", level="DEBUG")

        try:
            response = requests.get(station_url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            geometry = data.get('geometry')
            if geometry and geometry.get('type') == 'Point':
                coords = geometry.get('coordinates')
                if coords and len(coords) == 2:
                    if log_errors: self.log_to_gui(
                        f"Coordinates for {full_nws_station_id}: Lat={coords[1]}, Lon={coords[0]}", level="INFO")
                    return coords[1], coords[0]
            if log_errors: self.log_to_gui(f"Could not parse coordinates for {full_nws_station_id} from API response.",
                                           level="ERROR")
            return None
        except requests.exceptions.HTTPError as e:
            if log_errors:
                status_msg = f"Error: NWS Station '{full_nws_station_id}' not found." if e.response and e.response.status_code == 404 else f"Error: HTTP issue fetching NWS data for '{full_nws_station_id}'."
                self.log_to_gui(f"HTTP error fetching coordinates for {full_nws_station_id}: {e}", level="ERROR")
                self.update_status(status_msg)
            return None
        except requests.exceptions.RequestException as e:
            if log_errors:
                self.log_to_gui(f"Network error fetching coordinates for {full_nws_station_id}: {e}", level="ERROR")
                self.update_status(f"Error: Network issue fetching station data for {full_nws_station_id}.")
            return None
        except ValueError:
            if log_errors:
                self.log_to_gui(f"Invalid JSON response for {full_nws_station_id} coordinates.", level="ERROR")
                self.update_status(f"Error: Invalid NWS station data for {full_nws_station_id}.")
            return None
        except Exception as e:
            if log_errors: self.log_to_gui(f"Unexpected error fetching {full_nws_station_id} coordinates: {e}",
                                           level="ERROR")
            return None

    def _get_coordinates_for_location(self, location_input_str, log_errors=True):
        """
        Tries to get coordinates for a given location input, which can be
        a US zip code or an airport/NWS station ID.
        Args:
            location_input_str (str): The zip code or airport/NWS station ID.
            log_errors (bool): Whether to log errors.
        Returns:
            tuple: (latitude, longitude) if successful, otherwise None.
        """
        if not location_input_str:
            if log_errors: self.log_to_gui("Location input is empty.", level="ERROR")
            return None

        processed_input = location_input_str.strip().upper()

        # Try as US Zip Code (5 digits)
        if processed_input.isdigit() and len(processed_input) == 5:
            if log_errors: self.log_to_gui(f"Input '{processed_input}' looks like a zip code, attempting geocode.",
                                           level="DEBUG")
            coords = self._geocode_zip_to_coordinates(processed_input)
            if coords:
                return coords
            # If geocoding failed, it might be an unusual (all-digit) station ID. Fall through.

        # Try as Airport/NWS Station ID
        nws_id_to_try = processed_input
        if len(processed_input) == 3 and processed_input.isalpha():
            # Assume 3-letter airport ID, try with 'K' prefix for NWS (common for US)
            nws_id_to_try = "K" + processed_input
            if log_errors: self.log_to_gui(
                f"Input '{processed_input}' looks like 3-letter airport ID, trying NWS ID: {nws_id_to_try}",
                level="DEBUG")
        elif len(processed_input) == 4 and processed_input[0].isalpha() and processed_input[1:].isalnum():
            # Looks like a 4-char NWS ID (e.g., KSLE, PANC), use as is
            if log_errors: self.log_to_gui(f"Input '{processed_input}' looks like 4-char NWS ID, using as is.",
                                           level="DEBUG")

        coords = self._fetch_station_coordinates(nws_id_to_try, log_errors=log_errors)
        if coords:
            return coords

        # If a K-prefixed attempt for a 3-letter ID failed, and it wasn't the same as original input, try original 3-letter ID directly
        if len(processed_input) == 3 and processed_input.isalpha() and nws_id_to_try != processed_input:
            if log_errors: self.log_to_gui(
                f"NWS attempt for '{nws_id_to_try}' (from '{processed_input}') failed, trying '{processed_input}' directly.",
                level="DEBUG")
            coords_direct = self._fetch_station_coordinates(processed_input, log_errors=log_errors)
            if coords_direct:
                return coords_direct

        if log_errors:
            self.log_to_gui(
                f"Could not determine coordinates for location: '{location_input_str}'. Tried as zip and NWS station ID.",
                level="ERROR")
            self.update_status(f"Error: Could not find location '{location_input_str}'.")
        return None

    def _fetch_gridpoint_properties(self, latitude, longitude, log_errors=True):
        """
        Fetches NWS gridpoint properties (which include forecast URLs) for given coordinates.
        """
        if latitude is None or longitude is None: return None

        points_url = NWS_POINTS_API_URL_TEMPLATE.format(latitude=latitude, longitude=longitude)
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (github.com/nicarley/PythonWeatherAlerts)',
                   'Accept': 'application/geo+json'}
        if log_errors: self.log_to_gui(f"Fetching gridpoint properties from: {points_url}", level="DEBUG")

        try:
            response = requests.get(points_url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if log_errors: self.log_to_gui(f"Error fetching gridpoint properties: {e}", level="ERROR")
            return None
        except ValueError:
            if log_errors: self.log_to_gui(f"Invalid JSON response from gridpoint properties API.", level="ERROR")
            return None

    def _fetch_forecast_data_from_url(self, forecast_url, log_errors=True):
        """
        Fetches forecast data from a given NWS forecast URL.
        """
        if not forecast_url: return None

        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (github.com/nicarley/PythonWeatherAlerts)',
                   'Accept': 'application/geo+json'}
        if log_errors: self.log_to_gui(f"Fetching forecast data from: {forecast_url}", level="DEBUG")

        try:
            response = requests.get(forecast_url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if log_errors: self.log_to_gui(f"Error fetching forecast data from {forecast_url}: {e}", level="ERROR")
            return None
        except ValueError:
            if log_errors: self.log_to_gui(f"Invalid JSON response for forecast data from {forecast_url}.",
                                           level="ERROR")
            return None

    def _format_station_hourly_forecast_display(self, forecast_json):
        """
        Formats the hourly forecast data for display.
        """
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            return "8-Hour forecast data unavailable or malformed." # Changed
        periods = forecast_json['properties']['periods']
        display_text_parts = []
        for i, p in enumerate(periods):
            if i >= 8: break # Changed
            try:
                start_time_str = p.get('startTime', '')
                time_hm = start_time_str.split('T')[1].split(':')[0:2]
                formatted_time = f"{time_hm[0]}:{time_hm[1]}"
                temp = p.get('temperature', 'N/A')
                unit = p.get('temperatureUnit', '')
                short_fc = p.get('shortForecast', 'N/A')
                display_text_parts.append(f"{formatted_time}: {temp}°{unit}, {short_fc}")
            except (IndexError, AttributeError, TypeError) as e:
                self.log_to_gui(f"Error formatting hourly period: {p}, Error: {e}", level="WARNING")
                display_text_parts.append("Error: Malformed period data")

        return "\n".join(display_text_parts) if display_text_parts else "No 8-hour forecast periods found." # Changed

    def _format_daily_forecast_display(self, forecast_json):
        """
        Formats the daily forecast data for display.
        """
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            return "5-Day forecast data unavailable or malformed." # Changed
        periods = forecast_json['properties']['periods']
        display_text_parts = []
        for p in periods[:10]: # Changed (10 periods for 5 days, day/night)
            try:
                name = p.get('name', 'N/A')
                temp_label = "High" if "High" in name or p.get("isDaytime", False) else "Low"
                temp = f"{p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}"
                short_fc = p.get('shortForecast', 'N/A')
                display_text_parts.append(f"{name.replace(' Night', ' Nt')}: {temp_label} {temp}, {short_fc}")
            except (AttributeError, TypeError) as e:
                self.log_to_gui(f"Error formatting daily period: {p}, Error: {e}", level="WARNING")
                display_text_parts.append("Error: Malformed period data")

        return "\n".join(display_text_parts) if display_text_parts else "No 5-day forecast periods found." # Changed

    def _update_station_forecasts_display(self):
        """
        Fetches and updates both hourly and daily forecasts for the current location ID.
        """
        location_id = self.current_location_id  # Changed
        if not location_id:
            self.station_hourly_forecast_display_area.setText("Location ID not set.")
            self.daily_forecast_display_area.setText("Location ID not set.")
            self._adjust_forecast_text_area_sizes()
            return

        self.station_hourly_forecast_display_area.setText(f"Fetching 8-hour forecast for {location_id}...")  # Changed
        self.daily_forecast_display_area.setText(f"Fetching 5-day forecast for {location_id}...")  # Changed
        self._adjust_forecast_text_area_sizes()
        QApplication.processEvents()

        coords = self._get_coordinates_for_location(location_id, log_errors=False)  # Changed
        if not coords:
            msg = f"Could not get coordinates for {location_id} to fetch forecast."  # Changed
            self.station_hourly_forecast_display_area.setText(msg)
            self.daily_forecast_display_area.setText(msg)
            self._adjust_forecast_text_area_sizes()
            self.log_to_gui(msg, level="WARNING")
            return

        lat, lon = coords
        grid_props = self._fetch_gridpoint_properties(lat, lon, log_errors=False)
        if not grid_props or 'properties' not in grid_props:
            msg = f"Could not get NWS gridpoint (forecast URLs) for {location_id}."  # Changed
            self.station_hourly_forecast_display_area.setText(msg)
            self.daily_forecast_display_area.setText(msg)
            self._adjust_forecast_text_area_sizes()
            self.log_to_gui(msg, level="WARNING")
            return

        props = grid_props['properties']
        hourly_url = props.get('forecastHourly')
        if hourly_url:
            hourly_json = self._fetch_forecast_data_from_url(hourly_url, log_errors=False)
            self.station_hourly_forecast_display_area.setText(
                self._format_station_hourly_forecast_display(
                    hourly_json) if hourly_json else f"Could not retrieve 8-hour forecast for {location_id}.")  # Changed
        else:
            self.station_hourly_forecast_display_area.setText(
                f"8-hour forecast URL not found for {location_id}.")  # Changed
        self._adjust_forecast_text_area_sizes()

        daily_url = props.get('forecast')
        if daily_url:
            daily_json = self._fetch_forecast_data_from_url(daily_url, log_errors=False)
            self.daily_forecast_display_area.setText(
                self._format_daily_forecast_display(
                    daily_json) if daily_json else f"Could not retrieve 5-day forecast for {location_id}.")  # Changed
        else:
            self.daily_forecast_display_area.setText(f"5-day forecast URL not found for {location_id}.")  # Changed
        self._adjust_forecast_text_area_sizes()

    def _adjust_forecast_text_area_sizes(self):
        """Adjusts the geometry of forecast text areas to fit their content."""
        if hasattr(self, 'station_hourly_forecast_display_area'):
            self.station_hourly_forecast_display_area.document().adjustSize()
            self.station_hourly_forecast_display_area.updateGeometry()
        if hasattr(self, 'daily_forecast_display_area'):
            self.daily_forecast_display_area.document().adjustSize()
            self.daily_forecast_display_area.updateGeometry()

    def _get_current_weather_url(self, log_errors=True):
        """
        Constructs the NWS ATOM feed URL for active alerts based on the current location ID's coordinates.
        """
        location_id = self.current_location_id  # Changed
        if not location_id:
            if log_errors:
                self.log_to_gui("Location ID is empty. Cannot get weather alert URL.", level="ERROR")
                self.update_status("Error: Location ID not set for alerts.")
            return None

        coords = self._get_coordinates_for_location(location_id, log_errors=log_errors)  # Changed
        if coords:
            return f"{WEATHER_URL_PREFIX}{coords[0]}%2C{coords[1]}"
        if log_errors:
            self.log_to_gui(f"Failed to get coordinates for {location_id} to build alert URL.",
                            level="ERROR")  # Changed
        return None

    def _get_alerts(self, url):
        """
        Fetches and parses weather alerts from a given NWS ATOM feed URL.
        """
        if not url: return []

        self.log_to_gui(f"Fetching alerts from: {url}", level="DEBUG")
        headers = {'User-Agent': f'PyWeatherAlertGui/{versionnumber} (github.com/nicarley/PythonWeatherAlerts)'}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            self.log_to_gui(f"Fetched {len(feed.entries)} alert entries.", level="DEBUG")
            return feed.entries
        except requests.exceptions.Timeout:
            self.log_to_gui(f"Timeout occurred while fetching alerts from {url}.", level="ERROR")
        except requests.exceptions.HTTPError as e:
            self.log_to_gui(f"HTTP error fetching alerts from {url}: {e}", level="ERROR")
        except requests.exceptions.RequestException as e:
            self.log_to_gui(f"Error fetching alerts from {url}: {e}", level="ERROR")
        except Exception as e:
            self.log_to_gui(f"Unexpected error parsing alerts from {url}: {e}", level="ERROR")
        return []

    def _update_alerts_display_area(self, alerts):
        """
        Updates the alerts display area in the UI with the given list of alerts.
        """
        self.alerts_display_area.clear()
        location_id = self.current_location_id  # Changed
        loc_name = location_id if location_id else "the selected location"  # Changed

        if not alerts:
            self.alerts_display_area.setText(f"No active alerts for {loc_name}.")
        else:
            html_lines = []
            for a in alerts:
                title = a.get('title', 'N/A Title')
                color = 'black'
                if 'warning' in title.lower():
                    color = 'red'
                elif 'watch' in title.lower():
                    color = 'orange'
                elif 'advisory' in title.lower():
                    color = 'blue'
                html_lines.append(f"<strong style='color:{color};'>{title}</strong>")
            self.alerts_display_area.setHtml("<br>".join(html_lines))

        self.alerts_display_area.document().adjustSize()
        self.alerts_display_area.updateGeometry()

    def _speak_message_internal(self, text_to_speak, log_prefix="Spoken"):
        """
        Internal helper to speak a message using the TTS engine.
        """
        if not text_to_speak: return
        if self.is_tts_dummy:
            self.tts_engine.say(text_to_speak)
            return

        try:
            if self.tts_engine.isBusy():
                self.tts_engine.stop()
            self.tts_engine.say(text_to_speak)
            self.tts_engine.runAndWait()
            self.log_to_gui(f"{log_prefix}: {text_to_speak}", level="INFO")
        except Exception as e:
            self.log_to_gui(f"TTS error while trying to say '{text_to_speak[:50]}...': {e}", level="ERROR")

    def _speak_weather_alert(self, alert_title, alert_summary):
        """
        Constructs and speaks a weather alert message.
        """
        msg = f"Weather Alert: {alert_title}. Details: {alert_summary}"
        if self.current_repeater_info:
            msg += f". {self.current_repeater_info}"
        self._speak_message_internal(msg, log_prefix="Spoken Alert")

    def _speak_repeater_info(self):
        """Speaks the currently configured repeater information if available."""
        if self.current_repeater_info:
            self._speak_message_internal(self.current_repeater_info, log_prefix="Spoken Repeater Info")

    @Slot()
    def _on_speak_and_reset_button_press(self):
        """
        Handles the 'Speak Repeater Info & Reset Timer' action.
        """
        self.log_to_gui("Speak Repeater Info & Reset Timer button pressed.", level="INFO")
        if self.announce_alerts_action.isChecked():
            self._speak_repeater_info()

        self._update_main_timer_state()
        if self.main_check_timer.isActive():
            QTimer.singleShot(100, self.perform_check_cycle)
            self.update_status(f"Manual reset. Next check in ~{self.current_check_interval_ms // 60000} min.")
        else:
            self.update_status("Repeater info not spoken (Announce Alerts is off). Timed checks remain paused.")

    @Slot()
    def perform_check_cycle(self):
        """
        The main periodic task.
        """
        if not self.announce_alerts_action.isChecked() and not self.auto_refresh_action.isChecked():
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            if hasattr(self, 'top_countdown_label'):
                self.top_countdown_label.setText("Next Check: --:-- (Paused)")
            self.log_to_gui("All timed activities disabled. Skipping check cycle.", level="DEBUG")
            return

        self.main_check_timer.stop()

        if self.auto_refresh_action.isChecked():
            self._reload_radar_view()

        self._update_station_forecasts_display()

        location_id = self.current_location_id  # Changed
        self.log_to_gui(f"Performing periodic check for {location_id}...", level="INFO")  # Changed
        self.update_status(f"Checking {location_id}... (Last check started: {time.strftime('%H:%M:%S')})")  # Changed

        if self.announce_alerts_action.isChecked():
            alert_url = self._get_current_weather_url()
            alerts = self._get_alerts(alert_url) if alert_url else []
            self._update_alerts_display_area(alerts)

            new_alerts_found = False
            for alert in alerts:
                if not all(hasattr(alert, attr) for attr in ['id', 'title', 'summary']):
                    self.log_to_gui(f"Malformed alert entry skipped: {alert}", level="WARNING")
                    continue
                if alert.id not in self.seen_alert_ids:
                    new_alerts_found = True
                    self.log_to_gui(f"New Alert: {alert.title}", level="IMPORTANT")
                    self._speak_weather_alert(alert.title, alert.summary)
                    self.seen_alert_ids.add(alert.id)

            if not new_alerts_found and alert_url and alerts:
                self.log_to_gui(
                    f"No new alerts. Total active: {len(alerts)}. Total seen this session: {len(self.seen_alert_ids)}.",
                    level="INFO")
            elif not alerts and alert_url:
                self.log_to_gui(f"No active alerts found for {location_id}.", level="INFO")  # Changed
            self._speak_repeater_info()

        self.update_status(
            f"Check complete for {location_id}. Next check in ~{self.current_check_interval_ms // 60000} min.")  # Changed
        self.log_to_gui(
            f"Check cycle complete. Waiting {self.current_check_interval_ms // 1000} seconds for next cycle.",
            level="INFO")

        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
        if self.current_check_interval_ms > 0 and \
                (self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()):
            self.main_check_timer.start(self.current_check_interval_ms)

    def closeEvent(self, event):
        """
        Handles the window close event.
        """
        reply = QMessageBox.question(self, 'Quit Application', "Are you sure you want to quit Weather Alert Monitor?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log_to_gui("Shutting down application...", level="INFO")
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            if hasattr(self, 'clock_timer') and self.clock_timer:
                self.clock_timer.stop()  # Stop the clock timer
            if hasattr(self.tts_engine, 'stop') and not self.is_tts_dummy:
                try:
                    if self.tts_engine.isBusy():
                        self.tts_engine.stop()
                except Exception as e:
                    logging.error(f"Error stopping TTS engine during shutdown: {e}")
            self._save_settings()
            event.accept()
        else:
            event.ignore()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    if sys.platform == "darwin":
        logging.info("macOS detected. Using default Qt platform styling as base for light mode.")
    elif "Fusion" in QStyleFactory.keys():
        app.setStyle(QStyleFactory.create("Fusion"))
        logging.info("Applied Fusion style as base.")

    main_win = WeatherAlertApp()
    main_win._apply_color_scheme()
    main_win.show()
    sys.exit(app.exec())