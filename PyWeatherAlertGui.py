import sys
import pyttsx3
import time
import logging
import os
import json
import shutil
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Callable

# PySide6 imports
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QMessageBox,
    QStatusBar, QCheckBox, QSplitter, QStyleFactory, QGroupBox, QDialog,
    QDialogButtonBox, QFormLayout, QListWidget, QListWidgetItem, QLayout,
    QSpacerItem, QSizePolicy, QFileDialog, QFrame, QMenu, QStyle, QTableWidget,
    QTableWidgetItem, QHeaderView, QSystemTrayIcon, QTabWidget
)
from PySide6.QtCore import Qt, QTimer, Slot, QUrl, QFile, QTextStream, QObject, Signal, QRunnable, QThreadPool, QStandardPaths, QMarginsF, QSize
from PySide6.QtGui import (
    QTextCursor, QIcon, QColor, QDesktopServices, QPalette, QAction,
    QActionGroup, QFont, QPixmap, QFontDatabase
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None
    logging.warning("PySide6.QtWebEngineWidgets not found. Web view will be disabled.")

from weather_alert.api import NwsApiClient as ModularNwsApiClient, ApiError as ModularApiError
from weather_alert.history import AlertHistoryManager as ModularAlertHistoryManager
from weather_alert.settings import SettingsManager as ModularSettingsManager
from weather_alert.rules import (
    default_location_rules,
    evaluate_location_rule,
    normalize_location_entry,
    summarize_lifecycle,
)
from weather_alert.webhook import dispatch_notification_channels
from weather_alert.proximity import rank_alerts_by_proximity, distance_point_to_geometry_miles
from weather_alert.escalation import evaluate_escalation
from weather_alert.health import DeliveryHealthTracker
from weather_alert.dedup import AlertDeduplicator
from weather_alert.exporter import export_incident_csv, export_incident_json

# --- Application Version ---
versionnumber = "26.03.10"

# --- Constants ---
FALLBACK_INITIAL_CHECK_INTERVAL_MS = 900 * 1000
FALLBACK_DEFAULT_INTERVAL_KEY = "15 Minutes"
FALLBACK_DEFAULT_LOCATIONS = [{"name": "Default", "id": "62881", "rules": default_location_rules()}]
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
FALLBACK_SHOW_MONITORING_STATUS_CHECKED = True
FALLBACK_SHOW_LOCATION_OVERVIEW_CHECKED = True
FALLBACK_AUTO_REFRESH_CONTENT_CHECKED = False
FALLBACK_DARK_MODE_ENABLED = False
FALLBACK_LOG_SORT_ORDER = "chronological"
FALLBACK_MUTE_AUDIO_CHECKED = False
FALLBACK_ENABLE_SOUNDS = True
FALLBACK_ENABLE_DESKTOP_NOTIFICATIONS = True
FALLBACK_WEBHOOK_URL = ""
FALLBACK_ENABLE_WEBHOOK_NOTIFICATIONS = False
FALLBACK_DISCORD_WEBHOOK_URL = ""
FALLBACK_ENABLE_DISCORD_NOTIFICATIONS = False
FALLBACK_SLACK_WEBHOOK_URL = ""
FALLBACK_ENABLE_SLACK_NOTIFICATIONS = False
FALLBACK_ANNOUNCE_TIME_TOP = False
FALLBACK_ANNOUNCE_TIME_15 = False
FALLBACK_ANNOUNCE_TIME_30 = False
FALLBACK_ANNOUNCE_TIME_45 = False
FALLBACK_ANNOUNCE_TEMP_TOP = False
FALLBACK_ANNOUNCE_TEMP_15 = False
FALLBACK_ANNOUNCE_TEMP_30 = False
FALLBACK_ANNOUNCE_TEMP_45 = False

CHECK_INTERVAL_OPTIONS = {
    "1 Minute": 1 * 60 * 1000, "5 Minutes": 5 * 60 * 1000,
    "10 Minutes": 10 * 60 * 1000, "15 Minutes": 15 * 60 * 1000,
    "30 Minutes": 30 * 60 * 1000, "1 Hour": 60 * 60 * 1000,
}

NWS_STATION_API_URL_TEMPLATE = "https://api.weather.gov/stations/{station_id}"
NWS_POINTS_API_URL_TEMPLATE = "https://api.weather.gov/points/{latitude},{longitude}"
WEATHER_URL_PREFIX = "https://api.weather.gov/alerts/active.atom?point="
WEATHER_URL_SUFFIX = "&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Immediate%2CFuture%2CExpected"

SETTINGS_FILE_NAME = "settings.json"
RESOURCES_FOLDER_NAME = "resources"
ALERT_HISTORY_FILE = "alert_history.json"

ADD_NEW_SOURCE_TEXT = "Add New Source..."
MANAGE_SOURCES_TEXT = "Manage Sources..."
ADD_CURRENT_SOURCE_TEXT = "Add Current View as Source..."

MAX_HISTORY_ITEMS = 100
MANAGE_LOCATIONS_VALUE = "__manage_locations__"

# --- Stylesheet Content ---
LIGHT_STYLESHEET = '''
/*
 * Polished Light Modern Theme
 *
 * A refined and complete light theme with a consistent and professional look.
 * It includes support for more widgets, proper focus/disabled states,
 * and improved visual feedback.
 *
 * Color Palette:
 * - Primary Background:   #f0f0f0 (Light Gray)
 * - Secondary Background: #ffffff (White for GroupBoxes, Inputs)
 * - View Background:      #ffffff (TextEdit, ListWidget)
 * - Primary Text:         #212121 (Dark Gray)
 * - Muted Text:           #555555
 * - Border Color:         #cccccc
 * - Stronger Border:      #bbbbbb
 * - Primary Accent:       #3498db (Primary Blue)
 * - Secondary Accent:     #2980b9 (Darker Blue for Hover/Titles)
 * - Disabled Background:  #e9e9e9
 * - Disabled Text:        #a0a0a0
 * - High Temp:            #c0392b (Soft Red)
 * - Low Temp:             #2980b9 (Soft Blue)
 */

/* --- Global Styles --- */
QWidget {
    background-color: #f0f0f0;
    color: #212121;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    border: none;
}

QToolTip {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #cccccc;
    padding: 5px;
    border-radius: 4px;
}

/* --- Labels & Text --- */
QLabel {
    background-color: transparent;
    color: #333333;
}

QLabel:disabled {
    color: #a0a0a0;
}

/* --- GroupBox --- */
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 6px;
    margin-top: 1em; /* Make space for title */
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top center;
    padding: 0 10px;
    background-color: #f0f0f0;
    border-radius: 4px;
    color: #2980b9;
}

/* --- Text/List Views --- */
QTextEdit, QListWidget {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 4px;
    selection-background-color: #3498db;
    selection-color: #ffffff;
}

QTextEdit:focus, QListWidget:focus {
    border: 1px solid #3498db;
}

QListWidget::item {
    padding: 5px;
    border-radius: 3px;
}

QListWidget::item:alternate {
    background-color: #f7f7f7;
}

QListWidget::item:hover {
    background-color: #e9e9e9;
}

QListWidget::item:selected {
    background-color: #3498db;
    color: #ffffff;
}

/* --- Input Fields --- */
QLineEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 5px;
    padding-right: 24px;
    min-height: 20px;
    selection-background-color: #3498db;
    selection-color: #ffffff;
}

QLineEdit:hover, QComboBox:hover {
    border-color: #bbbbbb;
}

QLineEdit:focus, QComboBox:focus {
    border-color: #3498db;
}

QLineEdit:disabled, QComboBox:disabled {
    background-color: #e9e9e9;
    color: #a0a0a0;
    border-color: #dcdcdc;
}

/* --- ComboBox Specifics --- */
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left-width: 1px;
    border-left-color: #cccccc;
    border-left-style: solid;
    border-top-right-radius: 3px;
    border-bottom-right-radius: 3px;
}

QComboBox::drop-down:hover {
    background-color: #e9e9e9;
}

QComboBox::down-arrow {
    image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"><path fill="%234a5568" d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>');
    width: 12px;
    height: 12px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    selection-background-color: #3498db;
    color: #212121;
    padding: 2px;
}

/* --- Buttons --- */
QPushButton {
    background-color: #3498db;
    color: white;
    border: 1px solid #3498db;
    border-radius: 4px;
    padding: 6px 12px;
    min-width: 80px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #2980b9;
    border-color: #2980b9;
}

QPushButton:pressed {
    background-color: #1f618d;
}

QPushButton:focus {
    border-color: #2980b9;
    outline: 2px solid #a8d8f8; /* A light blue glow for focus */
}

QPushButton:disabled {
    background-color: #e9e9e9;
    color: #a0a0a0;
    border-color: #dcdcdc;
}

/* --- CheckBox & RadioButton --- */
QCheckBox, QRadioButton {
    background-color: transparent;
    spacing: 5px;
}

QCheckBox:disabled, QRadioButton:disabled {
    color: #a0a0a0;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #bbbbbb;
    border-radius: 3px;
    background-color: #ffffff;
}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: #a0a0a0;
}

QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    background-color: #e9e9e9;
    border-color: #dcdcdc;
}

QRadioButton::indicator {
    border-radius: 9px; /* Make it round */
}

QCheckBox::indicator:checked {
    background-color: #3498db;
    border-color: #3498db;
    /* A simple checkmark can be made with a local SVG for best results */
    /* image: url(resources/check_mark_light.svg); */
}

QRadioButton::indicator:checked {
    background-color: #ffffff;
    border: 2px solid #3498db;
}

QRadioButton::indicator:checked::after {
    content: '';
    display: block;
    position: relative;
    top: 2px;
    left: 2px;
    width: 8px;
    height: 8px;
    border-radius: 4px;
    background-color: #3498db;
}

/* --- Menu, Status, and Tool Bars --- */
QMenuBar {
    background-color: #e9e9e9;
    color: #212121;
}

QMenuBar::item {
    background: transparent;
    padding: 4px 8px;
}

QMenuBar::item:selected { /* Hover */
    background-color: #dcdcdc;
}

QMenuBar::item:pressed {
    background-color: #3498db;
    color: #ffffff;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    padding: 5px;
}

QMenu::item {
    padding: 5px 25px 5px 20px;
    border-radius: 4px;
}

QMenu::item:disabled {
    color: #a0a0a0;
}

QMenu::item:selected {
    background-color: #3498db;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background: #e0e0e0;
    margin: 5px 0;
}

QStatusBar {
    background-color: #e0e0e0;
    color: #555555;
}

/* --- ScrollBars --- */
QScrollBar:vertical {
    border: none;
    background: #e9e9e9;
    width: 12px;
    margin: 15px 0 15px 0;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background: #bbbbbb;
    min-height: 20px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover {
    background: #a0a0a0;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: none;
    height: 15px;
}

QScrollBar:horizontal {
    border: none;
    background: #e9e9e9;
    height: 12px;
    margin: 0 15px 0 15px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background: #bbbbbb;
    min-width: 20px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal:hover {
    background: #a0a0a0;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    border: none;
    background: none;
    width: 15px;
}

/* --- Tabs --- */
QTabWidget::pane {
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 8px;
}

QTabBar::tab {
    background: #e9e9e9;
    border: 1px solid #cccccc;
    border-bottom: none;
    padding: 8px 16px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: #555555;
}

QTabBar::tab:hover {
    background: #f0f0f0;
}

QTabBar::tab:selected {
    background: #ffffff;
    color: #212121;
    font-weight: bold;
}

/* --- Table / Tree Headers --- */
QHeaderView::section {
    background-color: #e9e9e9;
    padding: 4px;
    border: 1px solid #dcdcdc;
    font-weight: bold;
}

/* --- Custom Widget Styles --- */
/* These are preserved from your original file */

#DailyForecastWidget {
    background-color: #fafafa;
    border: 1px solid #e0e0e0;
    border-radius: 5px;
    margin: 4px 0;
}

#DailyForecastWidget:hover {
    background-color: #f0f5fa;
    border-color: #c0d0e0;
}

#DailyForecastWidget QLabel#highTemp {
    font-weight: bold;
    color: #c0392b; /* Soft Red */
}

#DailyForecastWidget QLabel#lowTemp {
    color: #2980b9; /* Soft Blue */
}

AlertWidget {
    border-radius: 5px;
    padding: 10px;
    margin: 5px 0;
    border: 1px solid transparent;
}

AlertWidget[severity="warning"] {
    background-color: #fff3cd;
    border-left: 5px solid #ffc107;
    color: #856404;
}

AlertWidget[severity="watch"] {
    background-color: #d1ecf1;
    border-left: 5px solid #17a2b8;
    color: #0c5460;
}

AlertWidget[severity="advisory"] {
    background-color: #e2e3e5;
    border-left: 5px solid #6c757d;
    color: #383d41;
}

AlertWidget QLabel {
    color: inherit;
    background-color: transparent;
}
'''

DARK_STYLESHEET = '''
/*
 * Polished Dark Modern Theme for PyWeatherAlert
 *
 * A refined and more complete version of the dark modern theme, with added
 * support for more widgets, focus/disabled states, and improved visual feedback.
 *
 * Color Palette:
 * - Primary Background:   #2d2d2d
 * - Secondary Background: #353535 (Groupboxes, etc.)
 * - Tertiary Background:  #3c3c3c (Inputs, Menus)
 * - View Background:      #252525 (TextEdit, ListWidget)
 * - Primary Text:         #f0f0f0
 * - Muted Text:           #a0a0a0
 * - Border Color:         #4a4a4a
 * - Stronger Border:      #555555
 * - Primary Accent:       #007acc (Blue for selection/highlight)
 * - Secondary Accent:     #00aaff (Lighter blue for titles/focus)
 * - Disabled Background:  #3a3a3a
 * - Disabled Text:        #888888
 */

/* --- Global Styles --- */
QWidget {
    background-color: #2d2d2d;
    color: #f0f0f0;
    font-family: "Segoe UI", "Helvetica Neue", "Arial", sans-serif;
    font-size: 10pt;
    border: none;
}

QToolTip {
    background-color: #252525;
    color: #f0f0f0;
    border: 1px solid #4a4a4a;
    padding: 5px;
    border-radius: 4px;
    opacity: 230; /* Make it slightly transparent */
}

/* --- Labels & Text --- */
QLabel {
    background-color: transparent;
}

QLabel#titleLabel { /* Example of a specific label for titles */
    font-size: 14pt;
    font-weight: bold;
    color: #00aaff;
}

QLabel:disabled {
    color: #888888;
}

/* --- GroupBox --- */
QGroupBox {
    background-color: #353535;
    border: 1px solid #4a4a4a;
    border-radius: 6px;
    margin-top: 1em; /* Make space for title */
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top center;
    padding: 0 10px;
    background-color: #353535;
    border-radius: 4px;
    color: #00aaff;
}

/* --- Text/List Views --- */
QTextEdit, QListView, QTreeView, QTableView {
    background-color: #252525;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    padding: 4px;
    color: #e0e0e0;
}

QTextEdit:focus, QListView:focus, QTreeView:focus, QTableView:focus {
    border: 1px solid #007acc;
}

QListView::item:alternate {
    background-color: #2a2a2a;
}

QListView::item:hover, QTreeView::item:hover {
    background-color: #3c3c3c;
}

QListView::item:selected, QTreeView::item:selected {
    background-color: #007acc;
    color: #ffffff;
}

/* --- Input Fields --- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 5px;
    min-height: 20px;
}

QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover, QTimeEdit:hover {
    border-color: #6a6a6a;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus {
    border-color: #007acc;
}

QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled {
    background-color: #3a3a3a;
    color: #888888;
    border-color: #4a4a4a;
}

/* --- ComboBox Specifics --- */
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left-width: 1px;
    border-left-color: #555555;
    border-left-style: solid;
    border-top-right-radius: 3px;
    border-bottom-right-radius: 3px;
}

QComboBox::drop-down:hover {
    background-color: #555555;
}

QComboBox::down-arrow {
    /* A sharp, scalable SVG arrow is better than a PNG */
    image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"><path fill="%23f0f0f0" d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>');
}

QComboBox QAbstractItemView {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    selection-background-color: #007acc;
    color: #f0f0f0;
    padding: 4px;
}

/* --- Buttons --- */
QPushButton {
    background-color: #555555;
    color: #f0f0f0;
    border: 1px solid #666666;
    border-radius: 4px;
    padding: 6px 12px;
    min-width: 80px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #6a6a6a;
    border-color: #777777;
}

QPushButton:pressed {
    background-color: #4a4a4a;
}

QPushButton:checked {
    background-color: #007acc;
    border-color: #005c99;
}

QPushButton:focus {
    border: 1px solid #00aaff;
    outline: none; /* Disable the default focus outline */
}

QPushButton:disabled {
    background-color: #3a3a3a;
    color: #888888;
    border-color: #4a4a4a;
}

/* --- CheckBox & RadioButton --- */
QCheckBox, QRadioButton {
    background-color: transparent;
    spacing: 8px;
}

QCheckBox:disabled, QRadioButton:disabled {
    color: #888888;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555555;
    border-radius: 3px;
    background-color: #3c3c3c;
}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: #6a6a6a;
}

QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    background-color: #3a3a3a;
    border-color: #4a4a4a;
}

QRadioButton::indicator {
    border-radius: 9px; /* Make it round */
}

QCheckBox::indicator:checked {
    background-color: #007acc;
    border-color: #007acc;
    /* Using an embedded SVG for a sharp checkmark */
    image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"><path fill="white" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>');
}

QRadioButton::indicator:checked {
    border: 2px solid #007acc;
    /* Create the inner dot using a radial gradient */
    background-color: qradialgradient(
        cx: 0.5, cy: 0.5, fx: 0.5, fy: 0.5, radius: 0.3,
        stop: 0 #00aaff, stop: 1 #3c3c3c
    );
}

/* --- Menu, Status, and Tool Bars --- */
QMenuBar {
    background-color: #3c3c3c;
    color: #f0f0f0;
}

QMenuBar::item {
    background: transparent;
    padding: 4px 10px;
}

QMenuBar::item:selected { /* Hover */
    background-color: #555555;
}

QMenuBar::item:pressed {
    background-color: #007acc;
}

QMenu {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    padding: 5px;
}

QMenu::item {
    padding: 5px 25px 5px 25px;
    border-radius: 4px;
}

QMenu::item:disabled {
    color: #888888;
}

QMenu::item:selected {
    background-color: #007acc;
}

QMenu::separator {
    height: 1px;
    background: #555555;
    margin: 5px 0;
}

QStatusBar {
    background-color: #3c3c3c;
    color: #f0f0f0;
}

/* --- ScrollBars --- */
QScrollBar:vertical {
    border: none;
    background: #2d2d2d;
    width: 12px;
    margin: 15px 0 15px 0;
}

QScrollBar::handle:vertical {
    background: #555555;
    min-height: 20px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover {
    background: #6a6a6a;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: none;
    height: 15px;
}

QScrollBar:horizontal {
    border: none;
    background: #2d2d2d;
    height: 12px;
    margin: 0 15px 0 15px;
}

QScrollBar::handle:horizontal {
    background: #555555;
    min-width: 20px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal:hover {
    background: #6a6a6a;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    border: none;
    background: none;
    width: 15px;
}

/* --- Sliders --- */
QSlider::groove:horizontal {
    border: 1px solid #4a4a4a;
    height: 4px;
    background: #3c3c3c;
    margin: 2px 0;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #00aaff;
    border: 1px solid #00aaff;
    width: 16px;
    height: 16px;
    margin: -8px 0;
    border-radius: 9px;
}

QSlider::groove:vertical {
    border: 1px solid #4a4a4a;
    width: 4px;
    background: #3c3c3c;
    margin: 0 2px;
    border-radius: 2px;
}

QSlider::handle:vertical {
    background: #00aaff;
    border: 1px solid #00aaff;
    height: 16px;
    width: 16px;
    margin: 0 -8px;
    border-radius: 9px;
}

/* --- Tab Widget --- */
QTabWidget::pane {
    border: 1px solid #4a4a4a;
    border-top: none;
    border-radius: 0 0 6px 6px;
}

QTabBar::tab {
    background: #353535;
    border: 1px solid #4a4a4a;
    border-bottom: none;
    padding: 8px 16px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}

QTabBar::tab:hover {
    background: #4a4a4a;
}

QTabBar::tab:selected {
    background: #2d2d2d;
    border-color: #4a4a4a;
    margin-bottom: -1px; /* Pull tab down to connect with pane */
}

/* --- Progress Bar --- */
QProgressBar {
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    text-align: center;
    color: #f0f0f0;
    background-color: #3c3c3c;
}

QProgressBar::chunk {
    background-color: #007acc;
    border-radius: 3px;
    margin: 1px;
}
'''


# --- Logging Configuration ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
IMPORTANT_LEVEL_NUM = logging.WARNING - 5
logging.addLevelName(IMPORTANT_LEVEL_NUM, "IMPORTANT")


def important(self, message, *args, **kws):
    if self.isEnabledFor(IMPORTANT_LEVEL_NUM):
        self._log(IMPORTANT_LEVEL_NUM, message, args, **kws)


logging.Logger.important = important


# --- Custom Exceptions ---
class ApiError(ModularApiError):
    """Backward-compatible alias for modular API exceptions."""
    pass


# --- Helper Classes ---
class AlertHistoryManager(ModularAlertHistoryManager):
    """Backward-compatible alias for modular history manager."""


class Worker(QRunnable):
    '''
    Worker thread for executing long-running tasks without blocking the UI.
    Inherits from QRunnable to be used with QThreadPool.
    '''

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


class SettingsManager(ModularSettingsManager):
    """Backward-compatible alias for modular settings manager."""


class NwsApiClient(ModularNwsApiClient):
    """Backward-compatible alias for modular NWS API client."""


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
                 current_id: Optional[str] = None, current_rules: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Location" if current_name else "Add New Location")
        self.layout = QFormLayout(self)
        self.parent_app = parent
        self.name_edit = QLineEdit(self)
        self.id_edit = QLineEdit(self)
        self.id_edit.setPlaceholderText("e.g., 62881, KSTL, 38.62,-90.19, ILC163, St Louis,MO")
        self.validation_label = QLabel("")
        self.validation_label.setStyleSheet("color: #555;")

        rules = current_rules if current_rules else default_location_rules()
        self.min_severity_combo = QComboBox()
        self.min_severity_combo.addItems(["Minor", "Moderate", "Severe", "Extreme"])
        self.min_severity_combo.setCurrentText(rules.get("min_severity", "Minor"))

        self.warning_check = QCheckBox("Warnings")
        self.watch_check = QCheckBox("Watches")
        self.advisory_check = QCheckBox("Advisories")
        enabled_types = set(rules.get("types", ["warning", "watch", "advisory"]))
        self.warning_check.setChecked("warning" in enabled_types)
        self.watch_check.setChecked("watch" in enabled_types)
        self.advisory_check.setChecked("advisory" in enabled_types)

        quiet_hours = rules.get("quiet_hours", {})
        self.quiet_hours_enabled = QCheckBox("Enable Quiet Hours")
        self.quiet_hours_enabled.setChecked(quiet_hours.get("enabled", False))
        self.quiet_start_edit = QLineEdit(quiet_hours.get("start", "22:00"))
        self.quiet_end_edit = QLineEdit(quiet_hours.get("end", "07:00"))
        self.quiet_start_edit.setPlaceholderText("HH:MM")
        self.quiet_end_edit.setPlaceholderText("HH:MM")

        self.desktop_override_combo = QComboBox()
        self.desktop_override_combo.addItems(["Use Global", "Force On", "Force Off"])
        desktop_pref = rules.get("desktop_notifications")
        if desktop_pref is True:
            self.desktop_override_combo.setCurrentText("Force On")
        elif desktop_pref is False:
            self.desktop_override_combo.setCurrentText("Force Off")

        self.sound_override_combo = QComboBox()
        self.sound_override_combo.addItems(["Use Global", "Force On", "Force Off"])
        sound_pref = rules.get("play_sounds")
        if sound_pref is True:
            self.sound_override_combo.setCurrentText("Force On")
        elif sound_pref is False:
            self.sound_override_combo.setCurrentText("Force Off")

        self.webhook_for_location_check = QCheckBox("Use Webhook For This Location")
        self.webhook_for_location_check.setChecked(rules.get("webhook_enabled", False))
        self.suppression_cooldown_edit = QLineEdit(str(rules.get("suppression_cooldown_seconds", 900)))
        self.suppression_cooldown_edit.setPlaceholderText("seconds")

        escalation_cfg = rules.get("escalation", {})
        self.escalation_enabled_check = QCheckBox("Enable Escalation")
        self.escalation_enabled_check.setChecked(escalation_cfg.get("enabled", True))
        self.escalation_min_severity_combo = QComboBox()
        self.escalation_min_severity_combo.addItems(["Moderate", "Severe", "Extreme"])
        self.escalation_min_severity_combo.setCurrentText(escalation_cfg.get("min_severity", "Severe"))
        self.escalation_radius_edit = QLineEdit(str(escalation_cfg.get("radius_miles", 40)))
        self.escalation_radius_edit.setPlaceholderText("miles")
        self.escalation_repeat_edit = QLineEdit(str(escalation_cfg.get("repeat_minutes", 5)))
        self.escalation_repeat_edit.setPlaceholderText("minutes")
        self.escalation_force_channels_check = QCheckBox("Escalation Forces All Channels")
        self.escalation_force_channels_check.setChecked(escalation_cfg.get("force_all_channels", True))

        if current_name: self.name_edit.setText(current_name)
        if current_id: self.id_edit.setText(current_id)
        self.layout.addRow("Location Name:", self.name_edit)
        self.layout.addRow("Location Input:", self.id_edit)
        self.layout.addRow("", self.validation_label)
        self.layout.addRow("Minimum Severity:", self.min_severity_combo)
        type_row = QWidget()
        type_row_layout = QHBoxLayout(type_row)
        type_row_layout.setContentsMargins(0, 0, 0, 0)
        type_row_layout.addWidget(self.warning_check)
        type_row_layout.addWidget(self.watch_check)
        type_row_layout.addWidget(self.advisory_check)
        self.layout.addRow("Alert Types:", type_row)
        self.layout.addRow(self.quiet_hours_enabled)
        quiet_row = QWidget()
        quiet_row_layout = QHBoxLayout(quiet_row)
        quiet_row_layout.setContentsMargins(0, 0, 0, 0)
        quiet_row_layout.addWidget(QLabel("Start"))
        quiet_row_layout.addWidget(self.quiet_start_edit)
        quiet_row_layout.addWidget(QLabel("End"))
        quiet_row_layout.addWidget(self.quiet_end_edit)
        self.layout.addRow("Quiet Hours:", quiet_row)
        self.layout.addRow("Desktop Notification:", self.desktop_override_combo)
        self.layout.addRow("Sound Behavior:", self.sound_override_combo)
        self.layout.addRow(self.webhook_for_location_check)
        self.layout.addRow("Notify Cooldown (s):", self.suppression_cooldown_edit)
        self.layout.addRow(self.escalation_enabled_check)
        self.layout.addRow("Escalate Min Severity:", self.escalation_min_severity_combo)
        self.layout.addRow("Escalate Radius (mi):", self.escalation_radius_edit)
        self.layout.addRow("Escalate Repeat (min):", self.escalation_repeat_edit)
        self.layout.addRow(self.escalation_force_channels_check)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        Qt.Orientation.Horizontal, self)
        validate_button = self.buttons.addButton("Validate", QDialogButtonBox.ButtonRole.ActionRole)
        validate_button.clicked.connect(self._validate_location_input)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def _validate_location_input(self):
        location_id = self.id_edit.text().strip()
        if hasattr(self.parent_app, "api_client"):
            is_valid, message = self.parent_app.api_client.validate_location(location_id)
            color = "green" if is_valid else "red"
            self.validation_label.setStyleSheet(f"color: {color};")
            self.validation_label.setText(message)
        else:
            self.validation_label.setText("Validation unavailable.")

    def _override_value(self, text: str) -> Optional[bool]:
        if text == "Force On":
            return True
        if text == "Force Off":
            return False
        return None

    def get_data(self) -> Optional[Dict[str, Any]]:
        name = self.name_edit.text().strip()
        location_id = self.id_edit.text().strip()
        if re.match(r"^[a-zA-Z]{3,4}$", location_id):
            location_id = location_id.upper()

        selected_types = []
        if self.warning_check.isChecked():
            selected_types.append("warning")
        if self.watch_check.isChecked():
            selected_types.append("watch")
        if self.advisory_check.isChecked():
            selected_types.append("advisory")

        if name and location_id:
            if not selected_types:
                QMessageBox.warning(self, "Invalid Input", "Enable at least one alert type.")
                return None
            try:
                suppression_cooldown_seconds = max(30, int(self.suppression_cooldown_edit.text().strip() or "900"))
                escalation_radius = max(1, int(float(self.escalation_radius_edit.text().strip() or "40")))
                escalation_repeat = max(1, int(float(self.escalation_repeat_edit.text().strip() or "5")))
            except ValueError:
                QMessageBox.warning(self, "Invalid Input", "Cooldown, radius, and repeat values must be numeric.")
                return None
            return normalize_location_entry(
                {
                    "name": name,
                    "id": location_id,
                    "rules": {
                        "min_severity": self.min_severity_combo.currentText(),
                        "types": selected_types,
                        "quiet_hours": {
                            "enabled": self.quiet_hours_enabled.isChecked(),
                            "start": self.quiet_start_edit.text().strip() or "22:00",
                            "end": self.quiet_end_edit.text().strip() or "07:00",
                        },
                        "desktop_notifications": self._override_value(self.desktop_override_combo.currentText()),
                        "play_sounds": self._override_value(self.sound_override_combo.currentText()),
                        "webhook_enabled": self.webhook_for_location_check.isChecked(),
                        "suppression_cooldown_seconds": suppression_cooldown_seconds,
                        "escalation": {
                            "enabled": self.escalation_enabled_check.isChecked(),
                            "min_severity": self.escalation_min_severity_combo.currentText(),
                            "radius_miles": escalation_radius,
                            "repeat_minutes": escalation_repeat,
                            "force_all_channels": self.escalation_force_channels_check.isChecked(),
                        },
                    },
                }
            )
        QMessageBox.warning(self, "Invalid Input", "Please provide a valid name and location ID.")
        return None


class ManageLocationsDialog(QDialog):
    def __init__(self, locations: List[Dict[str, Any]], parent: Optional[QWidget] = None, api_client=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Locations")
        self.locations: List[Dict[str, Any]] = [normalize_location_entry(loc) for loc in locations]
        self.api_client = api_client
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

        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(self.move_up_location)
        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(self.move_down_location)

        button_layout.addWidget(move_up_button)
        button_layout.addWidget(move_down_button)
        layout.addLayout(button_layout)

        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)

    def add_location(self):
        dialog = AddEditLocationDialog(self)
        dialog.parent_app = self
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data: return
            if any(loc['name'] == data["name"] for loc in self.locations):
                QMessageBox.warning(self, "Duplicate Name", f"A location with the name '{data['name']}' already exists.")
                return
            self.locations.append(data)
            self.list_widget.addItem(f"{data['name']} ({data['id']})")

    def edit_location(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item:
            return
        current_row = self.list_widget.currentRow()
        old_loc = self.locations[current_row]

        dialog = AddEditLocationDialog(
            self,
            current_name=old_loc['name'],
            current_id=old_loc['id'],
            current_rules=old_loc.get("rules", default_location_rules()),
        )
        dialog.parent_app = self
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data: return

            if data["name"] != old_loc['name'] and any(
                    loc['name'] == data["name"] for i, loc in enumerate(self.locations) if i != current_row):
                QMessageBox.warning(self, "Duplicate Name", f"A location with the name '{data['name']}' already exists.")
                return

            self.locations[current_row] = data
            selected_item.setText(f"{data['name']} ({data['id']})")

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

    def move_up_location(self):
        current_row = self.list_widget.currentRow()
        if current_row > 0:
            self.locations.insert(current_row - 1, self.locations.pop(current_row))
            self.list_widget.insertItem(current_row - 1, self.list_widget.takeItem(current_row))
            self.list_widget.setCurrentRow(current_row - 1)

    def move_down_location(self):
        current_row = self.list_widget.currentRow()
        if current_row < len(self.locations) - 1:
            self.locations.insert(current_row + 1, self.locations.pop(current_row))
            self.list_widget.insertItem(current_row + 1, self.list_widget.takeItem(current_row))
            self.list_widget.setCurrentRow(current_row + 1)

    def get_locations(self) -> List[Dict[str, Any]]:
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


class AlertDetailsDialog(QDialog):
    def __init__(self, alert_data: Dict[str, str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Alert Details")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        title_label = QLabel(f"<b>{alert_data.get('title', 'N/A')}</b>")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        layout.addSpacing(10)

        form_layout = QFormLayout()
        form_layout.addRow("Time:", QLabel(alert_data.get('time', 'N/A')))
        form_layout.addRow("Location:", QLabel(alert_data.get('location', 'N/A')))
        form_layout.addRow("Type:", QLabel(alert_data.get('type', 'N/A')))
        layout.addLayout(form_layout)

        layout.addSpacing(10)

        summary_group = QGroupBox("Summary")
        summary_layout = QVBoxLayout(summary_group)
        summary_text = QTextEdit()
        summary_text.setReadOnly(True)
        summary_text.setText(alert_data.get('summary', 'No summary available.'))
        summary_layout.addWidget(summary_text)
        layout.addWidget(summary_group)
        
        layout.addSpacing(10)

        link_label = QLabel()
        link = alert_data.get('link')
        if link:
            link_label.setText(f'<a href="{link}">Open original alert in browser</a>')
            link_label.setOpenExternalLinks(True)
        else:
            link_label.setText("No web link available.")
        link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(link_label)


        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setLayout(layout)


class AlertHistoryDialog(QDialog):
    def __init__(self, alert_manager: 'AlertHistoryManager', parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Alert History")
        self.setMinimumSize(700, 450)
        self.alert_manager = alert_manager
        history_data = self.alert_manager.get_recent_alerts(MAX_HISTORY_ITEMS)

        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Time", "Type", "Location", "Summary"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        for alert in history_data:
            row = self.table.rowCount()
            self.table.insertRow(row)
            time_item = QTableWidgetItem(alert.get('time', ''))
            time_item.setData(Qt.ItemDataRole.UserRole, alert)
            self.table.setItem(row, 0, time_item)
            self.table.setItem(row, 1, QTableWidgetItem(alert.get('type', '')))
            self.table.setItem(row, 2, QTableWidgetItem(alert.get('location', '')))
            self.table.setItem(row, 3, QTableWidgetItem(alert.get('summary', '')))

        button_layout = QHBoxLayout()
        read_more_button = QPushButton("Read More...")
        read_more_button.clicked.connect(self._read_more)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._delete_alert)
        clear_button = QPushButton("Clear All History")
        
        def clear_history_action():
            reply = QMessageBox.question(self, "Confirm Clear", "Are you sure you want to clear the entire alert history? This cannot be undone.")
            if reply == QMessageBox.StandardButton.Yes:
                self.alert_manager.clear_history()
                self.table.setRowCount(0)
                logging.info("Cleared all alert history.")
        
        clear_button.clicked.connect(clear_history_action)

        button_layout.addWidget(read_more_button)
        button_layout.addWidget(delete_button)
        button_layout.addStretch()
        button_layout.addWidget(clear_button)

        layout.addWidget(self.table)
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _read_more(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select an alert to read more.")
            return
        
        alert_data = self.table.item(self.table.currentRow(), 0).data(Qt.ItemDataRole.UserRole)
        if alert_data:
            dialog = AlertDetailsDialog(alert_data, self)
            dialog.exec()
        else:
            QMessageBox.warning(self, "Error", "Could not retrieve alert details.")

    def _delete_alert(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select an alert to delete.")
            return

        current_row = self.table.row(selected_items[0])
        alert_data = self.table.item(current_row, 0).data(Qt.ItemDataRole.UserRole)
        alert_id = alert_data.get('id')

        if not alert_id:
            QMessageBox.warning(self, "Error", "Could not identify the alert to delete.")
            return

        reply = QMessageBox.question(self, "Confirm Deletion", f"Are you sure you want to delete this alert from the history?\n\n- {alert_data.get('title', 'N/A')}")
        if reply == QMessageBox.StandardButton.Yes:
            self.alert_manager.remove_alert(alert_id)
            self.table.removeRow(current_row)
            logging.info(f"Deleted alert {alert_id} from history.")


class LifecycleTimelineDialog(QDialog):
    def __init__(self, alert_manager: 'AlertHistoryManager', location_id: str, location_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"Lifecycle Timeline - {location_name}")
        self.setMinimumSize(880, 500)

        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Time", "Lifecycle", "Severity", "Alert", "Change Summary"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        rows = alert_manager.get_recent_lifecycle(500, location_id=location_id)
        for event in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(event.get("time", "")))
            self.table.setItem(row, 1, QTableWidgetItem(event.get("lifecycle", "")))
            self.table.setItem(row, 2, QTableWidgetItem(event.get("severity", "")))
            self.table.setItem(row, 3, QTableWidgetItem(event.get("title", "")))
            self.table.setItem(row, 4, QTableWidgetItem(event.get("change_summary", "")))

        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(self.reject)
        close_btn.accepted.connect(self.accept)
        layout.addWidget(self.table)
        layout.addWidget(close_btn)
        self.setLayout(layout)


class DeliveryHealthDialog(QDialog):
    def __init__(self, tracker: DeliveryHealthTracker, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Delivery Health")
        self.setMinimumSize(760, 450)

        stats = tracker.stats()
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Channel", "Attempts", "Successes", "Failures", "Success %", "Last Error"])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for channel in sorted(stats.keys()):
            row = self.table.rowCount()
            self.table.insertRow(row)
            data = stats[channel]
            self.table.setItem(row, 0, QTableWidgetItem(channel))
            self.table.setItem(row, 1, QTableWidgetItem(str(data.get("attempts", 0))))
            self.table.setItem(row, 2, QTableWidgetItem(str(data.get("successes", 0))))
            self.table.setItem(row, 3, QTableWidgetItem(str(data.get("failures", 0))))
            self.table.setItem(row, 4, QTableWidgetItem(f"{data.get('success_rate', 0.0)}"))
            self.table.setItem(row, 5, QTableWidgetItem(data.get("last_error", "")))

        if self.table.rowCount() == 0:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem("No notification attempts yet."))
            for col in range(1, 6):
                self.table.setItem(0, col, QTableWidgetItem(""))

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        layout.addWidget(self.table)
        layout.addWidget(button_box)
        self.setLayout(layout)


class IncidentCenterDialog(QDialog):
    def __init__(
        self,
        alert_manager: 'AlertHistoryManager',
        tracker: DeliveryHealthTracker,
        location_id: str,
        location_name: str,
        parent: Optional[QWidget] = None,
        initial_tab: str = "Overview",
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Incident Center - {location_name}")
        self.resize(980, 680)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        history_rows = alert_manager.get_recent_alerts(25)
        timeline_rows = alert_manager.get_recent_lifecycle(25, location_id=location_id)
        delivery_stats = tracker.stats()
        total_failures = sum(int(data.get("failures", 0)) for data in delivery_stats.values())
        total_successes = sum(int(data.get("successes", 0)) for data in delivery_stats.values())

        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        overview_text = QTextEdit()
        overview_text.setReadOnly(True)
        lines = [
            f"Location: {location_name}",
            f"Recent alerts stored: {len(history_rows)}",
            f"Recent lifecycle events for this location: {len(timeline_rows)}",
            f"Notification successes tracked: {total_successes}",
            f"Notification failures tracked: {total_failures}",
            "",
            "Latest lifecycle events:",
        ]
        if timeline_rows:
            for event in timeline_rows[:8]:
                lines.append(
                    f"- {event.get('time', '')} [{event.get('lifecycle', '').upper()}] "
                    f"{event.get('title', '')} {event.get('change_summary', '')}".strip()
                )
        else:
            lines.append("- No lifecycle activity recorded yet for this location.")
        overview_text.setPlainText("\n".join(lines))
        overview_layout.addWidget(overview_text)
        self.tabs.addTab(overview_tab, "Overview")

        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        history_table = QTableWidget()
        history_table.setColumnCount(4)
        history_table.setHorizontalHeaderLabels(["Time", "Type", "Location", "Summary"])
        history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for alert in history_rows:
            row = history_table.rowCount()
            history_table.insertRow(row)
            history_table.setItem(row, 0, QTableWidgetItem(alert.get("time", "")))
            history_table.setItem(row, 1, QTableWidgetItem(alert.get("type", "")))
            history_table.setItem(row, 2, QTableWidgetItem(alert.get("location", "")))
            history_table.setItem(row, 3, QTableWidgetItem(alert.get("summary", "")))
        history_layout.addWidget(history_table)
        self.tabs.addTab(history_tab, "Alert History")

        timeline_tab = QWidget()
        timeline_layout = QVBoxLayout(timeline_tab)
        timeline_table = QTableWidget()
        timeline_table.setColumnCount(5)
        timeline_table.setHorizontalHeaderLabels(["Time", "Lifecycle", "Severity", "Alert", "Change Summary"])
        timeline_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        timeline_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        timeline_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for event in timeline_rows:
            row = timeline_table.rowCount()
            timeline_table.insertRow(row)
            timeline_table.setItem(row, 0, QTableWidgetItem(event.get("time", "")))
            timeline_table.setItem(row, 1, QTableWidgetItem(event.get("lifecycle", "")))
            timeline_table.setItem(row, 2, QTableWidgetItem(event.get("severity", "")))
            timeline_table.setItem(row, 3, QTableWidgetItem(event.get("title", "")))
            timeline_table.setItem(row, 4, QTableWidgetItem(event.get("change_summary", "")))
        timeline_layout.addWidget(timeline_table)
        self.tabs.addTab(timeline_tab, "Lifecycle")

        health_tab = QWidget()
        health_layout = QVBoxLayout(health_tab)
        health_table = QTableWidget()
        health_table.setColumnCount(6)
        health_table.setHorizontalHeaderLabels(["Channel", "Attempts", "Successes", "Failures", "Success %", "Last Error"])
        health_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        health_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for channel, data in sorted(delivery_stats.items()):
            row = health_table.rowCount()
            health_table.insertRow(row)
            health_table.setItem(row, 0, QTableWidgetItem(channel))
            health_table.setItem(row, 1, QTableWidgetItem(str(data.get("attempts", 0))))
            health_table.setItem(row, 2, QTableWidgetItem(str(data.get("successes", 0))))
            health_table.setItem(row, 3, QTableWidgetItem(str(data.get("failures", 0))))
            health_table.setItem(row, 4, QTableWidgetItem(str(data.get("success_rate", 0.0))))
            health_table.setItem(row, 5, QTableWidgetItem(data.get("last_error", "")))
        if health_table.rowCount() == 0:
            health_table.setRowCount(1)
            health_table.setItem(0, 0, QTableWidgetItem("No notification attempts yet."))
            for col in range(1, 6):
                health_table.setItem(0, col, QTableWidgetItem(""))
        health_layout.addWidget(health_table)
        self.tabs.addTab(health_tab, "Delivery Health")

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

        initial_index = 0
        for idx in range(self.tabs.count()):
            if self.tabs.tabText(idx).lower() == initial_tab.lower():
                initial_index = idx
                break
        self.tabs.setCurrentIndex(initial_index)


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        current_settings: Optional[Dict[str, Any]] = None,
        initial_tab: str = "General",
    ):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resize(820, 700)
        self.setMinimumSize(760, 620)
        self.current_settings = current_settings if current_settings else {}
        self.locations_data: List[Dict[str, Any]] = [
            normalize_location_entry(loc)
            for loc in self.current_settings.get("locations", FALLBACK_DEFAULT_LOCATIONS)
        ]

        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # --- General Settings ---
        general_tab = QWidget()
        form_layout = QFormLayout(general_tab)

        self.repeater_entry = QLineEdit(self.current_settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO))
        form_layout.addRow("Announcement:", self.repeater_entry)

        self.interval_combobox = QComboBox()
        self.interval_combobox.addItems(CHECK_INTERVAL_OPTIONS.keys())
        self.interval_combobox.setCurrentText(self.current_settings.get("interval_key", FALLBACK_DEFAULT_INTERVAL_KEY))
        form_layout.addRow("Check Interval:", self.interval_combobox)

        form_layout.addRow(QLabel("<b>Scheduled Time Announcements</b>"))
        self.announce_time_top_check = QCheckBox("Announce Time at :00")
        self.announce_time_top_check.setChecked(
            self.current_settings.get("announce_time_top", FALLBACK_ANNOUNCE_TIME_TOP)
        )
        self.announce_time_15_check = QCheckBox("Announce Time at :15")
        self.announce_time_15_check.setChecked(
            self.current_settings.get("announce_time_15", FALLBACK_ANNOUNCE_TIME_15)
        )
        self.announce_time_30_check = QCheckBox("Announce Time at :30")
        self.announce_time_30_check.setChecked(
            self.current_settings.get("announce_time_30", FALLBACK_ANNOUNCE_TIME_30)
        )
        self.announce_time_45_check = QCheckBox("Announce Time at :45")
        self.announce_time_45_check.setChecked(
            self.current_settings.get("announce_time_45", FALLBACK_ANNOUNCE_TIME_45)
        )
        form_layout.addRow(self.announce_time_top_check)
        form_layout.addRow(self.announce_time_15_check)
        form_layout.addRow(self.announce_time_30_check)
        form_layout.addRow(self.announce_time_45_check)

        form_layout.addRow(QLabel("<b>Scheduled Temperature Announcements</b>"))
        self.announce_temp_top_check = QCheckBox("Announce Temp at :00")
        self.announce_temp_top_check.setChecked(
            self.current_settings.get("announce_temp_top", FALLBACK_ANNOUNCE_TEMP_TOP)
        )
        self.announce_temp_15_check = QCheckBox("Announce Temp at :15")
        self.announce_temp_15_check.setChecked(
            self.current_settings.get("announce_temp_15", FALLBACK_ANNOUNCE_TEMP_15)
        )
        self.announce_temp_30_check = QCheckBox("Announce Temp at :30")
        self.announce_temp_30_check.setChecked(
            self.current_settings.get("announce_temp_30", FALLBACK_ANNOUNCE_TEMP_30)
        )
        self.announce_temp_45_check = QCheckBox("Announce Temp at :45")
        self.announce_temp_45_check.setChecked(
            self.current_settings.get("announce_temp_45", FALLBACK_ANNOUNCE_TEMP_45)
        )
        form_layout.addRow(self.announce_temp_top_check)
        form_layout.addRow(self.announce_temp_15_check)
        form_layout.addRow(self.announce_temp_30_check)
        form_layout.addRow(self.announce_temp_45_check)

        self.tabs.addTab(general_tab, "General")

        # --- Locations Tab ---
        locations_tab = QWidget()
        locations_layout = QVBoxLayout(locations_tab)
        self.locations_list_widget = QListWidget()
        locations_layout.addWidget(self.locations_list_widget)

        locations_button_layout = QHBoxLayout()
        add_button = QPushButton("Add...")
        add_button.clicked.connect(self._add_location)
        edit_button = QPushButton("Edit...")
        edit_button.clicked.connect(self._edit_location)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_location)
        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(self._move_up_location)
        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(self._move_down_location)
        locations_button_layout.addWidget(add_button)
        locations_button_layout.addWidget(edit_button)
        locations_button_layout.addWidget(remove_button)
        locations_button_layout.addStretch()
        locations_button_layout.addWidget(move_up_button)
        locations_button_layout.addWidget(move_down_button)
        locations_layout.addLayout(locations_button_layout)
        self.tabs.addTab(locations_tab, "Locations")
        self._refresh_locations_list()

        # --- Behavior Settings ---
        behavior_tab = QWidget()
        behavior_form_layout = QFormLayout(behavior_tab)

        self.announce_alerts_check = QCheckBox("Enable Timed Announcements")
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

        self.webhook_enable_check = QCheckBox("Enable Webhook Notifications")
        self.webhook_enable_check.setChecked(
            self.current_settings.get("enable_webhook_notifications", FALLBACK_ENABLE_WEBHOOK_NOTIFICATIONS)
        )
        behavior_form_layout.addRow(self.webhook_enable_check)

        self.webhook_url_entry = QLineEdit(self.current_settings.get("webhook_url", FALLBACK_WEBHOOK_URL))
        self.webhook_url_entry.setPlaceholderText("https://hooks.example.com/weather-alerts")
        behavior_form_layout.addRow("Webhook URL:", self.webhook_url_entry)

        self.discord_enable_check = QCheckBox("Enable Discord Notifications")
        self.discord_enable_check.setChecked(
            self.current_settings.get("enable_discord_notifications", FALLBACK_ENABLE_DISCORD_NOTIFICATIONS)
        )
        behavior_form_layout.addRow(self.discord_enable_check)

        self.discord_webhook_url_entry = QLineEdit(
            self.current_settings.get("discord_webhook_url", FALLBACK_DISCORD_WEBHOOK_URL)
        )
        self.discord_webhook_url_entry.setPlaceholderText("https://discord.com/api/webhooks/...")
        behavior_form_layout.addRow("Discord Webhook:", self.discord_webhook_url_entry)

        self.slack_enable_check = QCheckBox("Enable Slack Notifications")
        self.slack_enable_check.setChecked(
            self.current_settings.get("enable_slack_notifications", FALLBACK_ENABLE_SLACK_NOTIFICATIONS)
        )
        behavior_form_layout.addRow(self.slack_enable_check)

        self.slack_webhook_url_entry = QLineEdit(
            self.current_settings.get("slack_webhook_url", FALLBACK_SLACK_WEBHOOK_URL)
        )
        self.slack_webhook_url_entry.setPlaceholderText("https://hooks.slack.com/services/...")
        behavior_form_layout.addRow("Slack Webhook:", self.slack_webhook_url_entry)

        self.tabs.addTab(behavior_tab, "Behavior")

        # --- Display Settings ---
        display_tab = QWidget()
        display_form_layout = QFormLayout(display_tab)

        self.dark_mode_check = QCheckBox("Enable Dark Mode")
        self.dark_mode_check.setChecked(self.current_settings.get("dark_mode_enabled", FALLBACK_DARK_MODE_ENABLED))
        display_form_layout.addRow(self.dark_mode_check)

        display_form_layout.addRow(QFrame(frameShape=QFrame.Shape.HLine, frameShadow=QFrame.Shadow.Sunken))
        self.show_log_check = QCheckBox("Show Log Panel on Startup")
        self.show_log_check.setToolTip("Show or hide the log panel at the bottom of the window.")
        self.show_log_check.setChecked(self.current_settings.get("show_log", FALLBACK_SHOW_LOG_CHECKED))
        display_form_layout.addRow(self.show_log_check)

        self.show_alerts_check = QCheckBox("Show Current Alerts Area on Startup")
        self.show_alerts_check.setToolTip("Show or hide the Current Alerts panel.")
        self.show_alerts_check.setChecked(
            self.current_settings.get("show_alerts_area", FALLBACK_SHOW_ALERTS_AREA_CHECKED))
        display_form_layout.addRow(self.show_alerts_check)

        self.show_forecasts_check = QCheckBox("Show Weather Forecast Area on Startup")
        self.show_forecasts_check.setToolTip("Show or hide the Weather Forecast panel.")
        self.show_forecasts_check.setChecked(
            self.current_settings.get("show_forecasts_area", FALLBACK_SHOW_FORECASTS_AREA_CHECKED))
        display_form_layout.addRow(self.show_forecasts_check)

        display_form_layout.addRow(QFrame(frameShape=QFrame.Shape.HLine, frameShadow=QFrame.Shadow.Sunken))
        self.log_sort_combo = QComboBox()
        self.log_sort_combo.addItems(["Chronological", "Ascending", "Descending"])
        self.log_sort_combo.setCurrentText(
            self.current_settings.get("log_sort_order", FALLBACK_LOG_SORT_ORDER).capitalize())
        display_form_layout.addRow("Initial Log Sort Order:", self.log_sort_combo)
        self.tabs.addTab(display_tab, "Display")

        main_layout.addWidget(self.tabs)

        # --- Dialog Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        initial_index = 0
        for idx in range(self.tabs.count()):
            if self.tabs.tabText(idx).lower() == initial_tab.lower():
                initial_index = idx
                break
        self.tabs.setCurrentIndex(initial_index)

    def _refresh_locations_list(self):
        self.locations_list_widget.clear()
        for loc in self.locations_data:
            self.locations_list_widget.addItem(f"{loc['name']} ({loc['id']})")

    def _add_location(self):
        dialog = AddEditLocationDialog(self)
        dialog.parent_app = self.parent()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        if not data:
            return
        if any(loc["name"] == data["name"] for loc in self.locations_data):
            QMessageBox.warning(self, "Duplicate Name", f"A location with the name '{data['name']}' already exists.")
            return
        self.locations_data.append(data)
        self._refresh_locations_list()
        self.locations_list_widget.setCurrentRow(len(self.locations_data) - 1)

    def _edit_location(self):
        current_row = self.locations_list_widget.currentRow()
        if current_row < 0:
            return
        old_loc = self.locations_data[current_row]
        dialog = AddEditLocationDialog(
            self,
            current_name=old_loc["name"],
            current_id=old_loc["id"],
            current_rules=old_loc.get("rules", default_location_rules()),
        )
        dialog.parent_app = self.parent()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        if not data:
            return
        if data["name"] != old_loc["name"] and any(
            loc["name"] == data["name"] for i, loc in enumerate(self.locations_data) if i != current_row
        ):
            QMessageBox.warning(self, "Duplicate Name", f"A location with the name '{data['name']}' already exists.")
            return
        self.locations_data[current_row] = data
        self._refresh_locations_list()
        self.locations_list_widget.setCurrentRow(current_row)

    def _remove_location(self):
        current_row = self.locations_list_widget.currentRow()
        if current_row < 0:
            return
        if len(self.locations_data) <= 1:
            QMessageBox.warning(self, "Cannot Remove", "You must have at least one location.")
            return
        loc = self.locations_data[current_row]
        reply = QMessageBox.question(self, "Confirm Removal", f"Are you sure you want to remove '{loc['name']}'?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.locations_data.pop(current_row)
        self._refresh_locations_list()
        if self.locations_data:
            self.locations_list_widget.setCurrentRow(min(current_row, len(self.locations_data) - 1))

    def _move_up_location(self):
        current_row = self.locations_list_widget.currentRow()
        if current_row <= 0:
            return
        self.locations_data.insert(current_row - 1, self.locations_data.pop(current_row))
        self._refresh_locations_list()
        self.locations_list_widget.setCurrentRow(current_row - 1)

    def _move_down_location(self):
        current_row = self.locations_list_widget.currentRow()
        if current_row < 0 or current_row >= len(self.locations_data) - 1:
            return
        self.locations_data.insert(current_row + 1, self.locations_data.pop(current_row))
        self._refresh_locations_list()
        self.locations_list_widget.setCurrentRow(current_row + 1)

    def get_settings_data(self) -> Dict[str, Any]:
        return {
            "repeater_info": self.repeater_entry.text(),
            "locations": self.locations_data,
            "interval_key": self.interval_combobox.currentText(),
            "announce_alerts": self.announce_alerts_check.isChecked(),
            "announce_time_top": self.announce_time_top_check.isChecked(),
            "announce_time_15": self.announce_time_15_check.isChecked(),
            "announce_time_30": self.announce_time_30_check.isChecked(),
            "announce_time_45": self.announce_time_45_check.isChecked(),
            "announce_temp_top": self.announce_temp_top_check.isChecked(),
            "announce_temp_15": self.announce_temp_15_check.isChecked(),
            "announce_temp_30": self.announce_temp_30_check.isChecked(),
            "announce_temp_45": self.announce_temp_45_check.isChecked(),
            "auto_refresh_content": self.auto_refresh_check.isChecked(),
            "mute_audio": self.mute_audio_check.isChecked(),
            "enable_sounds": self.notification_sound_check.isChecked(),
            "enable_desktop_notifications": self.desktop_notification_check.isChecked(),
            "enable_webhook_notifications": self.webhook_enable_check.isChecked(),
            "webhook_url": self.webhook_url_entry.text().strip(),
            "enable_discord_notifications": self.discord_enable_check.isChecked(),
            "discord_webhook_url": self.discord_webhook_url_entry.text().strip(),
            "enable_slack_notifications": self.slack_enable_check.isChecked(),
            "slack_webhook_url": self.slack_webhook_url_entry.text().strip(),
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

        self.api_client = ModularNwsApiClient(f'PyWeatherAlertGui/{versionnumber} (github.com/nicarley/PythonWeatherAlerts)')
        self.settings_manager = ModularSettingsManager(os.path.join(self._get_user_data_path(), SETTINGS_FILE_NAME))
        self.alert_history_manager = ModularAlertHistoryManager(
            os.path.join(self._get_user_data_path(), ALERT_HISTORY_FILE))
        self.thread_pool = QThreadPool()
        self.log_to_gui(f"Multithreading with up to {self.thread_pool.maxThreadCount()} threads.", level="DEBUG")

        self.current_coords: Optional[Tuple[float, float]] = None
        self.last_known_data_by_location: Dict[str, Dict[str, Any]] = {}
        self.last_active_alerts_by_location: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.delivery_health = DeliveryHealthTracker(max_events=1000)
        self.alert_dedup = AlertDeduplicator(default_cooldown_s=900)
        self.last_escalated_alert_time: Dict[str, float] = {}
        self.current_alerts_by_location: Dict[str, List[Dict[str, Any]]] = {}
        self.escalation_repeat_state: Dict[str, Dict[str, Any]] = {}
        self.last_lifecycle_by_location: Dict[str, Dict[str, Any]] = {}
        self.location_runtime_status: Dict[str, Dict[str, Any]] = {}

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
        self.current_show_monitoring_status_checked = FALLBACK_SHOW_MONITORING_STATUS_CHECKED
        self.current_show_location_overview_checked = FALLBACK_SHOW_LOCATION_OVERVIEW_CHECKED
        self.current_auto_refresh_content_checked = FALLBACK_AUTO_REFRESH_CONTENT_CHECKED
        self.current_dark_mode_enabled = FALLBACK_DARK_MODE_ENABLED
        self.current_log_sort_order = FALLBACK_LOG_SORT_ORDER
        self.current_mute_audio_checked = FALLBACK_MUTE_AUDIO_CHECKED
        self.current_enable_sounds = FALLBACK_ENABLE_SOUNDS
        self.current_enable_desktop_notifications = FALLBACK_ENABLE_DESKTOP_NOTIFICATIONS
        self.current_webhook_url = FALLBACK_WEBHOOK_URL
        self.current_enable_webhook_notifications = FALLBACK_ENABLE_WEBHOOK_NOTIFICATIONS
        self.current_discord_webhook_url = FALLBACK_DISCORD_WEBHOOK_URL
        self.current_enable_discord_notifications = FALLBACK_ENABLE_DISCORD_NOTIFICATIONS
        self.current_slack_webhook_url = FALLBACK_SLACK_WEBHOOK_URL
        self.current_enable_slack_notifications = FALLBACK_ENABLE_SLACK_NOTIFICATIONS
        self.current_announce_time_top = FALLBACK_ANNOUNCE_TIME_TOP
        self.current_announce_time_15 = FALLBACK_ANNOUNCE_TIME_15
        self.current_announce_time_30 = FALLBACK_ANNOUNCE_TIME_30
        self.current_announce_time_45 = FALLBACK_ANNOUNCE_TIME_45
        self.current_announce_temp_top = FALLBACK_ANNOUNCE_TEMP_TOP
        self.current_announce_temp_15 = FALLBACK_ANNOUNCE_TEMP_15
        self.current_announce_temp_30 = FALLBACK_ANNOUNCE_TEMP_30
        self.current_announce_temp_45 = FALLBACK_ANNOUNCE_TEMP_45
        self.latest_temperature_reading: Optional[str] = None
        self._last_time_announcement_minute_key: Optional[str] = None
        self._last_temp_announcement_minute_key: Optional[str] = None

        self._load_settings()
        self._set_window_icon()

        self.tts_engine = self._initialize_tts_engine()
        self.is_tts_dummy = isinstance(self.tts_engine, self._DummyEngine)

        self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(
            self.current_interval_key, FALLBACK_INITIAL_CHECK_INTERVAL_MS)

        self.main_check_timer = QTimer(self)
        self.main_check_timer.setSingleShot(True)
        self.main_check_timer.timeout.connect(self.perform_check_cycle)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_countdown_display)
        self.remaining_time_seconds = 0
        self._check_in_progress = False
        self._pending_location_id: Optional[str] = None
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_current_time_display)
        self.scheduled_announcement_timer = QTimer(self)
        self.scheduled_announcement_timer.timeout.connect(self._check_scheduled_time_and_temperature_announcements)

        self._init_ui()
        self._apply_loaded_settings_to_ui()

        self.log_to_gui(f"Monitoring Location: {self.get_current_location_name()}", level="INFO")
        self._update_location_data(self.current_location_id)
        self._update_main_timer_state()

        # Start the clock timer
        self.clock_timer.start(1000)
        self.scheduled_announcement_timer.start(15000)
        self._update_current_time_display()

    def get_current_location_name(self):
        for loc in self.locations:
            if loc["id"] == self.current_location_id:
                return loc["name"]
        return "Unknown"

    def _severity_rank(self, severity: str) -> int:
        order = {"Unknown": 0, "Minor": 1, "Moderate": 2, "Severe": 3, "Extreme": 4}
        return order.get(str(severity or "Unknown"), 0)

    def _active_escalation_count(self, location_id: str) -> int:
        count = 0
        for data in self.escalation_repeat_state.values():
            if data.get("location_id") == location_id:
                count += 1
        return count

    def _describe_location_health(self, location_id: str) -> str:
        status = self.location_runtime_status.get(location_id, {})
        state = status.get("state", "idle")
        if state == "online":
            fetched_at = status.get("fetched_at")
            if fetched_at:
                age_seconds = int(max(time.time() - fetched_at, 0))
                return f"Online · refreshed {age_seconds // 60}m ago"
            return "Online"
        if state == "cached":
            return status.get("detail", "Cached data in use")
        if state == "error":
            return status.get("detail", "Refresh failed")
        return "Awaiting first refresh"

    def _location_summary_text(self, location_id: str) -> str:
        alerts = self.current_alerts_by_location.get(location_id, [])
        highest = "None"
        if alerts:
            highest_alert = max(alerts, key=lambda alert: self._severity_rank(alert.get("severity", "Unknown")))
            highest = highest_alert.get("severity", "Unknown")
        return (
            f"{len(alerts)} active · "
            f"{self._active_escalation_count(location_id)} escalated · "
            f"highest {highest}"
        )

    def _describe_location_escalation(self, location_id: str) -> str:
        location_cfg = next((loc for loc in self.locations if loc.get("id") == location_id), {})
        escalation_cfg = location_cfg.get("rules", {}).get("escalation", {})
        if not escalation_cfg.get("enabled", True):
            return "Escalation off"

        min_severity = escalation_cfg.get("min_severity", "Severe")
        radius_miles = escalation_cfg.get("radius_miles", 40)
        repeat_minutes = escalation_cfg.get("repeat_minutes", 5)
        active_count = self._active_escalation_count(location_id)
        active_text = "no active repeats" if active_count == 0 else f"{active_count} repeating"
        return (
            f"Escalates {min_severity}+ within {radius_miles} mi"
            f" · repeats every {repeat_minutes}m"
            f" · {active_text}"
        )

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
        """Gets the path to bundled, read-only resources like icons and stylesheets."""
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Running in a PyInstaller bundle.
            base_path = sys._MEIPASS
        else:
            # Running in a normal Python environment
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, RESOURCES_FOLDER_NAME)

    def _get_user_data_path(self) -> str:
        """Gets a writable path for user data (settings, history)."""
        app_name = "PythonWeatherAlerts"
        # Use Qt's standard paths for cross-platform compatibility
        # On macOS, this is ~/Library/Application Support/
        path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        if app_name not in path:
            path = os.path.join(path, app_name)
        os.makedirs(path, exist_ok=True)
        return path
        
    def _load_settings(self):
        settings = self.settings_manager.load()
        if not settings:
            self._apply_fallback_settings("Settings file not found or invalid. Using defaults.")
            return

        self.current_repeater_info = settings.get("repeater_info", FALLBACK_INITIAL_REPEATER_INFO)
        self.locations = [normalize_location_entry(loc) for loc in settings.get("locations", FALLBACK_DEFAULT_LOCATIONS)]
        saved_location_id = settings.get("current_location_id")
        if self.locations:
            valid_location_ids = {loc.get("id") for loc in self.locations}
            self.current_location_id = saved_location_id if saved_location_id in valid_location_ids else self.locations[0].get("id")
        else:
            self.locations = [normalize_location_entry(loc) for loc in FALLBACK_DEFAULT_LOCATIONS]
            self.current_location_id = self.locations[0].get("id")
        self.current_interval_key = settings.get("check_interval_key", FALLBACK_DEFAULT_INTERVAL_KEY)
        radar_options = settings.get("radar_options_dict", DEFAULT_RADAR_OPTIONS.copy())
        self.RADAR_OPTIONS = radar_options if isinstance(radar_options, dict) and radar_options else DEFAULT_RADAR_OPTIONS.copy()
        self.current_radar_url = settings.get("radar_url", FALLBACK_DEFAULT_RADAR_URL)
        if self.current_radar_url not in self.RADAR_OPTIONS.values():
            self.current_radar_url = next(iter(self.RADAR_OPTIONS.values()), FALLBACK_DEFAULT_RADAR_URL)
        self.current_announce_alerts_checked = settings.get("announce_alerts", FALLBACK_ANNOUNCE_ALERTS_CHECKED)
        self.current_show_log_checked = settings.get("show_log", FALLBACK_SHOW_LOG_CHECKED)
        self.current_show_alerts_area_checked = settings.get("show_alerts_area", FALLBACK_SHOW_ALERTS_AREA_CHECKED)
        self.current_show_forecasts_area_checked = settings.get("show_forecasts_area",
                                                                FALLBACK_SHOW_FORECASTS_AREA_CHECKED)
        self.current_show_monitoring_status_checked = settings.get(
            "show_monitoring_status", FALLBACK_SHOW_MONITORING_STATUS_CHECKED
        )
        self.current_show_location_overview_checked = settings.get(
            "show_location_overview", FALLBACK_SHOW_LOCATION_OVERVIEW_CHECKED
        )
        self.current_auto_refresh_content_checked = settings.get("auto_refresh_content",
                                                                 FALLBACK_AUTO_REFRESH_CONTENT_CHECKED)
        self.current_dark_mode_enabled = settings.get("dark_mode_enabled", FALLBACK_DARK_MODE_ENABLED)
        self.current_log_sort_order = settings.get("log_sort_order", FALLBACK_LOG_SORT_ORDER)
        self.current_mute_audio_checked = settings.get("mute_audio", FALLBACK_MUTE_AUDIO_CHECKED)
        self.current_enable_sounds = settings.get("enable_sounds", FALLBACK_ENABLE_SOUNDS)
        self.current_enable_desktop_notifications = settings.get("enable_desktop_notifications", FALLBACK_ENABLE_DESKTOP_NOTIFICATIONS)
        self.current_webhook_url = settings.get("webhook_url", FALLBACK_WEBHOOK_URL)
        self.current_enable_webhook_notifications = settings.get("enable_webhook_notifications", FALLBACK_ENABLE_WEBHOOK_NOTIFICATIONS)
        self.current_discord_webhook_url = settings.get("discord_webhook_url", FALLBACK_DISCORD_WEBHOOK_URL)
        self.current_enable_discord_notifications = settings.get("enable_discord_notifications", FALLBACK_ENABLE_DISCORD_NOTIFICATIONS)
        self.current_slack_webhook_url = settings.get("slack_webhook_url", FALLBACK_SLACK_WEBHOOK_URL)
        self.current_enable_slack_notifications = settings.get("enable_slack_notifications", FALLBACK_ENABLE_SLACK_NOTIFICATIONS)
        self.current_announce_time_top = settings.get("announce_time_top", FALLBACK_ANNOUNCE_TIME_TOP)
        self.current_announce_time_15 = settings.get("announce_time_15", FALLBACK_ANNOUNCE_TIME_15)
        self.current_announce_time_30 = settings.get("announce_time_30", FALLBACK_ANNOUNCE_TIME_30)
        self.current_announce_time_45 = settings.get("announce_time_45", FALLBACK_ANNOUNCE_TIME_45)
        self.current_announce_temp_top = settings.get("announce_temp_top", FALLBACK_ANNOUNCE_TEMP_TOP)
        self.current_announce_temp_15 = settings.get("announce_temp_15", FALLBACK_ANNOUNCE_TEMP_15)
        self.current_announce_temp_30 = settings.get("announce_temp_30", FALLBACK_ANNOUNCE_TEMP_30)
        self.current_announce_temp_45 = settings.get("announce_temp_45", FALLBACK_ANNOUNCE_TEMP_45)

        self._last_valid_radar_text = self._get_display_name_for_url(self.current_radar_url) or \
                                      (list(self.RADAR_OPTIONS.keys())[0] if self.RADAR_OPTIONS else "")

    def _apply_fallback_settings(self, reason_message: str):
        self.log_to_gui(reason_message, level="WARNING")
        self.current_repeater_info = FALLBACK_INITIAL_REPEATER_INFO
        self.locations = [normalize_location_entry(loc) for loc in FALLBACK_DEFAULT_LOCATIONS]
        self.current_location_id = self.locations[0]["id"]
        self.current_interval_key = FALLBACK_DEFAULT_INTERVAL_KEY
        self.RADAR_OPTIONS = DEFAULT_RADAR_OPTIONS.copy()
        self.current_radar_url = FALLBACK_DEFAULT_RADAR_URL
        self._last_valid_radar_text = FALLBACK_DEFAULT_RADAR_DISPLAY_NAME
        self.current_announce_alerts_checked = FALLBACK_ANNOUNCE_ALERTS_CHECKED
        self.current_show_log_checked = FALLBACK_SHOW_LOG_CHECKED
        self.current_show_alerts_area_checked = FALLBACK_SHOW_ALERTS_AREA_CHECKED
        self.current_show_forecasts_area_checked = FALLBACK_SHOW_FORECASTS_AREA_CHECKED
        self.current_show_monitoring_status_checked = FALLBACK_SHOW_MONITORING_STATUS_CHECKED
        self.current_show_location_overview_checked = FALLBACK_SHOW_LOCATION_OVERVIEW_CHECKED
        self.current_auto_refresh_content_checked = FALLBACK_AUTO_REFRESH_CONTENT_CHECKED
        self.current_dark_mode_enabled = FALLBACK_DARK_MODE_ENABLED
        self.current_log_sort_order = FALLBACK_LOG_SORT_ORDER
        self.current_mute_audio_checked = FALLBACK_MUTE_AUDIO_CHECKED
        self.current_enable_sounds = FALLBACK_ENABLE_SOUNDS
        self.current_enable_desktop_notifications = FALLBACK_ENABLE_DESKTOP_NOTIFICATIONS
        self.current_webhook_url = FALLBACK_WEBHOOK_URL
        self.current_enable_webhook_notifications = FALLBACK_ENABLE_WEBHOOK_NOTIFICATIONS
        self.current_discord_webhook_url = FALLBACK_DISCORD_WEBHOOK_URL
        self.current_enable_discord_notifications = FALLBACK_ENABLE_DISCORD_NOTIFICATIONS
        self.current_slack_webhook_url = FALLBACK_SLACK_WEBHOOK_URL
        self.current_enable_slack_notifications = FALLBACK_ENABLE_SLACK_NOTIFICATIONS
        self.current_announce_time_top = FALLBACK_ANNOUNCE_TIME_TOP
        self.current_announce_time_15 = FALLBACK_ANNOUNCE_TIME_15
        self.current_announce_time_30 = FALLBACK_ANNOUNCE_TIME_30
        self.current_announce_time_45 = FALLBACK_ANNOUNCE_TIME_45
        self.current_announce_temp_top = FALLBACK_ANNOUNCE_TEMP_TOP
        self.current_announce_temp_15 = FALLBACK_ANNOUNCE_TEMP_15
        self.current_announce_temp_30 = FALLBACK_ANNOUNCE_TEMP_30
        self.current_announce_temp_45 = FALLBACK_ANNOUNCE_TEMP_45

    @Slot()
    def _save_settings(self):
        settings = {
            "repeater_info": self.current_repeater_info,
            "locations": [normalize_location_entry(loc) for loc in self.locations],
            "current_location_id": self.current_location_id,
            "check_interval_key": self.current_interval_key,
            "radar_options_dict": self.RADAR_OPTIONS,
            "radar_url": self.current_radar_url,
            "announce_alerts": self.announce_alerts_action.isChecked(),
            "announce_time_top": self.current_announce_time_top,
            "announce_time_15": self.current_announce_time_15,
            "announce_time_30": self.current_announce_time_30,
            "announce_time_45": self.current_announce_time_45,
            "announce_temp_top": self.current_announce_temp_top,
            "announce_temp_15": self.current_announce_temp_15,
            "announce_temp_30": self.current_announce_temp_30,
            "announce_temp_45": self.current_announce_temp_45,
            "auto_refresh_content": self.auto_refresh_action.isChecked(),
            "mute_audio": self.mute_action.isChecked(),
            "enable_sounds": self.enable_sounds_action.isChecked(),
            "enable_desktop_notifications": self.desktop_notification_action.isChecked(),
            "webhook_url": self.current_webhook_url,
            "enable_webhook_notifications": self.current_enable_webhook_notifications,
            "discord_webhook_url": self.current_discord_webhook_url,
            "enable_discord_notifications": self.current_enable_discord_notifications,
            "slack_webhook_url": self.current_slack_webhook_url,
            "enable_slack_notifications": self.current_enable_slack_notifications,
            "dark_mode_enabled": self.dark_mode_action.isChecked(),
            "show_log": self.show_log_action.isChecked(),
            "show_alerts_area": self.show_alerts_area_action.isChecked(),
            "show_forecasts_area": self.show_forecasts_area_action.isChecked(),
            "show_monitoring_status": self.show_monitoring_status_action.isChecked(),
            "show_location_overview": self.show_location_overview_action.isChecked(),
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
        main_layout.setSpacing(15) # Increased spacing
        main_layout.setContentsMargins(15, 15, 15, 15) # Added margins

        # --- Top Status Bar ---
        top_status_layout = self._create_top_status_bar()
        main_layout.addLayout(top_status_layout)

        # --- Dashboard Overview ---
        self.dashboard_overview_panel = self._create_dashboard_overview()
        main_layout.addWidget(self.dashboard_overview_panel)

        # --- Menu Bar ---
        self._create_menu_bar()
        self.web_source_quick_select_button.setMenu(self.web_sources_menu)

        # --- Main Content Area (Alerts & Forecasts) ---
        self.alerts_forecasts_container = QWidget()
        self.alerts_forecasts_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        alerts_forecasts_layout = QHBoxLayout(self.alerts_forecasts_container)
        alerts_forecasts_layout.setContentsMargins(0,0,0,0)
        alerts_forecasts_layout.setSpacing(6)
        main_layout.addWidget(self.alerts_forecasts_container, 1) # Stretch factor 1

        # Alerts Group
        self.alerts_group = QGroupBox("Now")
        self.alerts_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        alerts_layout = QVBoxLayout(self.alerts_group)
        alerts_layout.setContentsMargins(5, 5, 5, 5)
        alerts_layout.setSpacing(4)
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(4)
        self.all_alerts_button = QPushButton("All", checkable=True, checked=True)
        self.warning_button = QPushButton("Warnings", checkable=True)
        self.watch_button = QPushButton("Watches", checkable=True)
        self.advisory_button = QPushButton("Advisories", checkable=True)
        for btn in [self.all_alerts_button, self.warning_button, self.watch_button, self.advisory_button]:
            btn.clicked.connect(self._filter_alerts)
            btn.setMaximumHeight(24)
            filter_layout.addWidget(btn)
        alerts_layout.addLayout(filter_layout)
        self.alerts_display_area = QListWidget()
        self.alerts_display_area.setObjectName("AlertsDisplayArea")
        self.alerts_display_area.setWordWrap(False)
        self.alerts_display_area.setUniformItemSizes(True)
        self.alerts_display_area.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.alerts_display_area.setAlternatingRowColors(True)
        self.alerts_display_area.setSpacing(1)
        self.alerts_display_area.setMaximumHeight(180)
        alerts_layout.addWidget(self.alerts_display_area)

        lifecycle_header = QLabel("<b>Alert Lifecycle</b>")
        alerts_layout.addWidget(lifecycle_header)
        self.lifecycle_display_area = QListWidget()
        self.lifecycle_display_area.setObjectName("LifecycleDisplayArea")
        self.lifecycle_display_area.setWordWrap(False)
        self.lifecycle_display_area.setUniformItemSizes(True)
        self.lifecycle_display_area.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.lifecycle_display_area.setAlternatingRowColors(True)
        self.lifecycle_display_area.setSpacing(1)
        self.lifecycle_display_area.setMaximumHeight(90)
        alerts_layout.addWidget(self.lifecycle_display_area)
        alerts_forecasts_layout.addWidget(self.alerts_group, 1)

        # Combined Forecasts Group
        self.combined_forecast_widget = QGroupBox("Soon")
        self.combined_forecast_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        combined_forecast_main_layout = QHBoxLayout(self.combined_forecast_widget)
        combined_forecast_main_layout.setContentsMargins(2, 2, 2, 2)
        combined_forecast_main_layout.setSpacing(3)
        hourly_forecast_sub_group = QGroupBox("8-Hour Forecast")
        hourly_forecast_sub_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        hourly_forecast_sub_group_layout = QVBoxLayout(hourly_forecast_sub_group)
        hourly_forecast_sub_group_layout.setContentsMargins(1, 1, 1, 1)
        hourly_forecast_sub_group_layout.setSpacing(1)
        self.hourly_forecast_widget = QWidget()
        self.hourly_forecast_layout = QGridLayout(self.hourly_forecast_widget)
        self.hourly_forecast_layout.setContentsMargins(0, 0, 0, 0)
        self.hourly_forecast_layout.setHorizontalSpacing(8)
        self.hourly_forecast_layout.setVerticalSpacing(1)
        self.hourly_forecast_layout.setColumnStretch(0, 2)
        self.hourly_forecast_layout.setColumnStretch(1, 1)
        self.hourly_forecast_layout.setColumnStretch(2, 1)
        self.hourly_forecast_layout.setColumnStretch(3, 2)
        self.hourly_forecast_layout.setColumnStretch(4, 1)
        self.hourly_forecast_layout.setColumnStretch(5, 1)
        self.hourly_forecast_layout.setColumnStretch(6, 1)
        self.hourly_forecast_layout.setColumnStretch(7, 1)
        self.hourly_forecast_layout.setColumnStretch(8, 4)
        hourly_font = QFont(); hourly_font.setPointSize(8); self.hourly_forecast_widget.setFont(hourly_font)
        hourly_forecast_sub_group_layout.addWidget(self.hourly_forecast_widget)
        combined_forecast_main_layout.addWidget(hourly_forecast_sub_group, 1)
        daily_forecast_sub_group = QGroupBox("5-Day Forecast")
        daily_forecast_sub_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        daily_forecast_sub_group_layout = QVBoxLayout(daily_forecast_sub_group)
        daily_forecast_sub_group_layout.setContentsMargins(1, 1, 1, 1)
        daily_forecast_sub_group_layout.setSpacing(1)
        self.daily_forecast_widget = QWidget()
        self.daily_forecast_layout = QGridLayout(self.daily_forecast_widget)
        self.daily_forecast_layout.setContentsMargins(0, 0, 0, 0)
        self.daily_forecast_layout.setHorizontalSpacing(8)
        self.daily_forecast_layout.setVerticalSpacing(1)
        self.daily_forecast_layout.setColumnStretch(0, 2)
        self.daily_forecast_layout.setColumnStretch(1, 1)
        self.daily_forecast_layout.setColumnStretch(2, 2)
        self.daily_forecast_layout.setColumnStretch(3, 1)
        self.daily_forecast_layout.setColumnStretch(4, 4)
        daily_font = QFont(); daily_font.setPointSize(8); self.daily_forecast_widget.setFont(daily_font)
        daily_forecast_sub_group_layout.addWidget(self.daily_forecast_widget)
        combined_forecast_main_layout.addWidget(daily_forecast_sub_group, 1)
        alerts_forecasts_layout.addWidget(self.combined_forecast_widget, 2)

        # --- Bottom Splitter (Web View & Log) ---
        self.bottom_splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(self.bottom_splitter, 3) # Stretch factor 3

        self.web_tabs = QTabWidget()
        if QWebEngineView:
            self.web_view = QWebEngineView()
            self.map_view = QWebEngineView()
            self.nws_view = QWebEngineView()
            self.web_tabs.addTab(self.web_view, "Web Source")
            self.web_tabs.addTab(self.map_view, "Alert Map")
            self.web_tabs.addTab(self.nws_view, "NWS")
        else:
            self.web_view = QLabel("WebEngineView not available. Please install 'PySide6-WebEngine'.")
            self.web_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.map_view = QLabel("Map view unavailable without PySide6-WebEngine.")
            self.map_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.nws_view = QLabel("NWS view unavailable without PySide6-WebEngine.")
            self.nws_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.web_tabs.addTab(self.web_view, "Web Source")
            self.web_tabs.addTab(self.map_view, "Alert Map")
            self.web_tabs.addTab(self.nws_view, "NWS")
        self.bottom_splitter.addWidget(self.web_tabs)

        self.log_widget = QWidget()
        log_layout = QVBoxLayout(self.log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_toolbar = QHBoxLayout()
        log_toolbar.addWidget(QLabel("<b>Application Log</b>"))
        log_toolbar.addStretch()
        style = self.style()
        sort_asc_button = QPushButton("Sort Asc"); sort_asc_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp)); sort_asc_button.setToolTip("Sort log ascending (A-Z)"); sort_asc_button.clicked.connect(self._sort_log_ascending); log_toolbar.addWidget(sort_asc_button)
        sort_desc_button = QPushButton("Sort Desc"); sort_desc_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)); sort_desc_button.setToolTip("Sort log descending (Z-A)"); sort_desc_button.clicked.connect(self._sort_log_descending); log_toolbar.addWidget(sort_desc_button)
        clear_log_button = QPushButton("Clear Log"); clear_log_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)); clear_log_button.clicked.connect(lambda: self.log_area.clear()); log_toolbar.addWidget(clear_log_button)
        log_layout.addLayout(log_toolbar)
        self.log_area = QTextEdit(); self.log_area.setReadOnly(True); log_layout.addWidget(self.log_area)
        self.bottom_splitter.addWidget(self.log_widget)

        if self._log_buffer:
            self.log_area.append("\n".join(self._log_buffer))
            self._log_buffer.clear()

        self.bottom_splitter.setSizes([400, 200])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.network_status_indicator = QLabel("● Network OK")
        self.network_status_indicator.setStyleSheet("color: green; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.network_status_indicator)

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
        self.top_repeater_label = QLabel("Announcement: N/A")
        self.top_countdown_label = QLabel("Next Check: --:--")
        self.last_announcement_label = QLabel("Last Announcement: --")
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
        self.location_combo.setMinimumWidth(220)
        self.location_combo.setToolTip("Select a location to view")
        self.location_combo.currentIndexChanged.connect(self._on_location_selected)
        top_status_layout.addWidget(self.location_combo)

        top_status_layout.addSpacing(20)

        interval_icon_label = QLabel()
        interval_icon_label.setPixmap(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload).pixmap(16, 16))
        top_status_layout.addWidget(interval_icon_label)

        self.top_interval_combo = QComboBox()
        self.top_interval_combo.addItems(CHECK_INTERVAL_OPTIONS.keys())
        self.top_interval_combo.setMinimumWidth(130)
        self.top_interval_combo.setToolTip("Set check interval")
        self.top_interval_combo.currentTextChanged.connect(self._on_top_interval_changed)
        top_status_layout.addWidget(self.top_interval_combo)
        top_status_layout.addSpacing(10)

        self.web_source_quick_select_button = QPushButton("Web Source")
        self.web_source_quick_select_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.web_source_quick_select_button.setToolTip("Quick select web source")
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
        top_status_layout.addWidget(self.last_announcement_label)
        top_status_layout.addSpacing(15)
        top_status_layout.addWidget(self.current_time_label)

        return top_status_layout

    def _create_summary_card(self, title: str, accent: str) -> Tuple[QFrame, QLabel, QLabel]:
        card = QFrame()
        card.setObjectName("OverviewCard")
        card.setStyleSheet(
            f"#OverviewCard {{ border: 1px solid #c7d0d9; border-radius: 10px; background: #ffffff; }}"
            f"#OverviewCard QLabel[role='value'] {{ color: {accent}; font-size: 20px; font-weight: bold; }}"
            "#OverviewCard QLabel[role='title'] { color: #5b6773; text-transform: uppercase; font-size: 10px; font-weight: bold; }"
            "#OverviewCard QLabel[role='detail'] { color: #334155; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setProperty("role", "title")
        value_label = QLabel("--")
        value_label.setProperty("role", "value")
        detail_label = QLabel("Waiting for data")
        detail_label.setWordWrap(True)
        detail_label.setProperty("role", "detail")

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)
        return card, value_label, detail_label

    def _create_dashboard_overview(self) -> QWidget:
        panel = QGroupBox("Operational Overview")
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        self.dashboard_header_widget = QWidget()
        header_layout = QVBoxLayout(self.dashboard_header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        self.dashboard_headline = QLabel("Now monitoring current location")
        self.dashboard_headline.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.dashboard_subheadline = QLabel("Alerts, escalation, and delivery health are summarized here.")
        self.dashboard_subheadline.setWordWrap(True)
        header_layout.addWidget(self.dashboard_headline)
        header_layout.addWidget(self.dashboard_subheadline)
        layout.addWidget(self.dashboard_header_widget)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(10)
        active_card, self.active_alerts_value_label, self.active_alerts_detail_label = self._create_summary_card("Active Alerts", "#b91c1c")
        escalation_card, self.escalations_value_label, self.escalations_detail_label = self._create_summary_card("Escalations", "#c2410c")
        network_card, self.data_state_value_label, self.data_state_detail_label = self._create_summary_card("Data State", "#0369a1")
        delivery_card, self.delivery_value_label, self.delivery_detail_label = self._create_summary_card("Notifications", "#047857")
        cards_layout.addWidget(active_card, 1)
        cards_layout.addWidget(escalation_card, 1)
        cards_layout.addWidget(network_card, 1)
        cards_layout.addWidget(delivery_card, 1)
        layout.addLayout(cards_layout)

        self.location_overview_header = QLabel("<b>Location Overview</b>")
        footer_layout = QHBoxLayout()
        footer_layout.addWidget(self.location_overview_header)
        footer_layout.addStretch(1)
        incident_button = QPushButton("Open Incident Center")
        incident_button.clicked.connect(lambda checked=False: self._show_incident_center())
        footer_layout.addWidget(incident_button)
        layout.addLayout(footer_layout)

        self.location_overview_list = QListWidget()
        self.location_overview_list.setMaximumHeight(140)
        self.location_overview_list.itemClicked.connect(self._on_location_overview_clicked)
        layout.addWidget(self.location_overview_list)
        return panel

    def _create_menu_bar(self):
        menu_bar = self.menuBar()
        style = self.style()

        # File Menu
        file_menu = menu_bar.addMenu("&File")
        preferences_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
                                     "&Preferences...", self)
        preferences_action.triggered.connect(lambda _checked=False: self._open_preferences_dialog("General"))
        file_menu.addAction(preferences_action)
        file_menu.addSeparator()
        self.file_show_monitoring_status_action = QAction("Show Operational Status", self, checkable=True)
        self.file_show_monitoring_status_action.toggled.connect(self._on_show_monitoring_status_toggled)
        file_menu.addAction(self.file_show_monitoring_status_action)
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
        self.web_sources_menu.aboutToShow.connect(self._update_web_sources_menu)
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
        self.show_monitoring_status_action = QAction("Show Monitoring Status", self, checkable=True)
        self.show_monitoring_status_action.toggled.connect(self._on_show_monitoring_status_toggled)
        view_menu.addAction(self.show_monitoring_status_action)
        self.show_location_overview_action = QAction("Show Location Overview", self, checkable=True)
        self.show_location_overview_action.toggled.connect(self._on_show_location_overview_toggled)
        view_menu.addAction(self.show_location_overview_action)
        view_menu.addSeparator()
        self.dark_mode_action = QAction("&Enable Dark Mode", self, checkable=True)
        self.dark_mode_action.toggled.connect(self._on_dark_mode_toggled)
        view_menu.addAction(self.dark_mode_action)

        # History Menu
        history_menu = menu_bar.addMenu("&History")
        incident_center_action = QAction("Open Incident Center", self)
        incident_center_action.triggered.connect(lambda checked=False: self._show_incident_center())
        history_menu.addAction(incident_center_action)
        history_menu.addSeparator()
        view_history_action = QAction("View Alert History", self)
        view_history_action.triggered.connect(self._show_alert_history)
        history_menu.addAction(view_history_action)
        view_timeline_action = QAction("View Lifecycle Timeline", self)
        view_timeline_action.triggered.connect(self._show_lifecycle_timeline)
        history_menu.addAction(view_timeline_action)
        export_incident_action = QAction("Export Incident Report...", self)
        export_incident_action.triggered.connect(self._export_incident_report)
        history_menu.addAction(export_incident_action)

        # Actions Menu
        actions_menu = menu_bar.addMenu("&Actions")
        self.announce_alerts_action = QAction("Enable Timed Announcements", self, checkable=True)
        self.announce_alerts_action.setToolTip("When checked, periodically announces repeater info or new alerts at the set interval.")
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
        health_action = QAction("Delivery Health Dashboard", self)
        health_action.triggered.connect(lambda: self._show_incident_center("Delivery Health"))
        actions_menu.addAction(health_action)
        test_channels_action = QAction("Send Test Notifications", self)
        test_channels_action.triggered.connect(self._send_test_notifications)
        actions_menu.addAction(test_channels_action)

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

    def get_weather_emoji(self, forecast_text: str) -> str:
        """Returns an emoji based on the forecast text."""
        text = forecast_text.lower()
        if 'sunny' in text or 'clear' in text:
            return "☀️"
        elif 'partly cloudy' in text:
            return "⛅"
        elif 'cloudy' in text or 'overcast' in text:
            return "☁️"
        elif 'rain' in text or 'shower' in text:
            return "🌧️"
        elif 'thunderstorm' in text or 't-storm' in text:
            return "⛈️"
        elif 'snow' in text or 'flurries' in text:
            return "❄️"
        elif 'fog' in text or 'mist' in text:
            return "🌫️"
        elif 'wind' in text or 'breezy' in text:
            return "💨"
        else:
            return "🌡️"

    @staticmethod
    def _compact_text(value: Any, max_len: int = 90) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_len:
            return text
        return f"{text[: max_len - 1].rstrip()}…"

    def _make_compact_label(self, text: str, tooltip: Optional[str] = None) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(False)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        label.setMinimumWidth(0)
        label.setMaximumHeight(label.fontMetrics().height() + 4)
        if tooltip:
            label.setToolTip(tooltip)
        return label

    def _apply_forecast_cell_style(self, label: QLabel, row_index: int, is_header: bool = False) -> QLabel:
        palette = self.palette()
        if is_header:
            bg = palette.alternateBase().color().name()
            border = palette.mid().color().name()
            label.setStyleSheet(
                f"padding: 2px 5px; background-color: {bg}; border-bottom: 1px solid {border}; font-weight: 600;"
            )
        else:
            bg_role = palette.alternateBase() if row_index % 2 else palette.base()
            bg = bg_role.color().name()
            border = palette.midlight().color().name()
            label.setStyleSheet(
                f"padding: 1px 5px; background-color: {bg}; border-bottom: 1px solid {border};"
            )
        return label

    def _update_location_data(self, location_id):
        if self._check_in_progress:
            self._pending_location_id = location_id
            self.log_to_gui("A check is already running; queued latest location refresh request.", level="DEBUG")
            return

        self._check_in_progress = True
        self.location_runtime_status[location_id] = {"state": "loading", "detail": "Refreshing from NWS"}
        self._update_dashboard_summary()
        self.update_status(f"Fetching data for {self.get_location_name_by_id(location_id)}...")
        self._clear_and_set_loading_states()

        worker = Worker(self._fetch_all_data_for_location, location_id)
        worker.signals.result.connect(self._on_location_data_loaded)
        worker.signals.error.connect(self._on_data_load_error)
        self.thread_pool.start(worker)

    def _schedule_next_timed_check(self, immediate: bool = False):
        is_active = self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()
        if not is_active:
            self.main_check_timer.stop()
            self.countdown_timer.stop()
            self.top_countdown_label.setText("Next Check: --:-- (Paused)")
            return

        if self.current_check_interval_ms <= 0:
            self.top_countdown_label.setText("Next Check: --:-- (Invalid Interval)")
            return

        self.main_check_timer.stop()
        if immediate:
            self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
            QTimer.singleShot(100, self.perform_check_cycle)
            return

        self.main_check_timer.start(self.current_check_interval_ms)
        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)

    def _finish_check_cycle(self):
        self._check_in_progress = False
        if self._pending_location_id:
            queued_location = self._pending_location_id
            self._pending_location_id = None
            self._update_location_data(queued_location)
            return
        self._schedule_next_timed_check(immediate=False)

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
            raise ModularApiError(f"Could not retrieve forecast URLs for {lat},{lon}. API might be down or rate-limited.")

        hourly_forecast = None
        daily_forecast = None
        grid_forecast = None

        if forecast_urls.get("hourly"):
            hourly_forecast = self.api_client.get_forecast_data(forecast_urls["hourly"])
            if not hourly_forecast:
                raise ModularApiError(f"Failed to fetch hourly forecast data from {forecast_urls['hourly']}.")

        if forecast_urls.get("daily"):
            daily_forecast = self.api_client.get_forecast_data(forecast_urls["daily"])
            if not daily_forecast:
                raise ModularApiError(f"Failed to fetch daily forecast data from {forecast_urls['daily']}.")

        if forecast_urls.get("grid"):
            grid_forecast = self.api_client.get_forecast_data(forecast_urls["grid"])

        return {
            "location_id": location_id,
            "coords": coords,
            "alerts": alerts,
            "hourly_forecast": hourly_forecast,
            "daily_forecast": daily_forecast,
            "grid_forecast": grid_forecast,
            "fetched_at": time.time(),
        }

    @Slot(object)
    def _on_location_data_loaded(self, result: Dict[str, Any]):
        self.network_status_indicator.setText("● Network OK")
        self.network_status_indicator.setStyleSheet("color: green; font-weight: bold;")
        self.current_coords = result["coords"]
        alerts = result["alerts"]
        if self.current_coords:
            alerts = rank_alerts_by_proximity(alerts, self.current_coords[0], self.current_coords[1])
        location_id = result["location_id"]
        previous = self.last_active_alerts_by_location.get(location_id, {})
        lifecycle = summarize_lifecycle(previous, alerts)
        self.last_active_alerts_by_location[location_id] = lifecycle["active"]
        self.current_alerts_by_location[location_id] = alerts
        self.last_lifecycle_by_location[location_id] = lifecycle
        self.last_known_data_by_location[location_id] = result
        self.location_runtime_status[location_id] = {
            "state": "online",
            "detail": f"{len(alerts)} active alerts",
            "fetched_at": result.get("fetched_at"),
        }
        self._record_lifecycle_events(location_id, lifecycle)

        self.log_to_gui(f"Successfully fetched data for {self.get_location_name_by_id(location_id)} at {self.current_coords}",
                        level="INFO")
        if lifecycle["new"] or lifecycle["updated"] or lifecycle["expired"] or lifecycle["cancelled"]:
            self.log_to_gui(
                f"Lifecycle: +{len(lifecycle['new'])} new, {len(lifecycle['updated'])} updated, "
                f"{len(lifecycle['expired'])} expired, {len(lifecycle['cancelled'])} cancelled.",
                level="INFO",
            )
            for update in lifecycle["updated"][:3]:
                self.log_to_gui(f"Updated alert: {update['title']} | {'; '.join(update['changes'])}", level="INFO")

        self._update_alerts_display_area(alerts, location_id, lifecycle)
        new_alert_titles = [alert.get("title", "N/A Title") for alert in lifecycle["new"] if alert.get("_notify_allowed")]
        self._update_lifecycle_display(lifecycle)
        self._update_hourly_forecast_display(result["hourly_forecast"], result.get("grid_forecast"))
        self._update_daily_forecast_display(result["daily_forecast"], result.get("grid_forecast"))
        self._update_alert_map(alerts)
        self._update_nws_tab()
        self._update_dashboard_summary()
        self.update_status(f"Data for {self.get_location_name_by_id(location_id)} updated.")

        self._handle_timed_announcements(new_alert_titles, location_id)
        self._dispatch_webhooks_for_location(location_id, lifecycle["new"])
        self._finish_check_cycle()

    @Slot(Exception)
    def _on_data_load_error(self, e: Exception):
        self.network_status_indicator.setText("● Network FAIL")
        self.network_status_indicator.setStyleSheet("color: red; font-weight: bold;")
        self.log_to_gui(str(e), level="ERROR")
        self.update_status(f"Error: {e}. Showing last known data if available.")
        cached = self.last_known_data_by_location.get(self.current_location_id)
        if cached:
            fetched_at = cached.get("fetched_at")
            stale_text = ""
            if fetched_at:
                stale_seconds = int(max(time.time() - fetched_at, 0))
                stale_text = f", stale {stale_seconds // 60}m {stale_seconds % 60}s"
            self.network_status_indicator.setText(f"● Offline (Using Cached Data{stale_text})")
            self.network_status_indicator.setStyleSheet("color: #b58900; font-weight: bold;")
            self.current_coords = cached.get("coords")
            self.location_runtime_status[self.current_location_id] = {
                "state": "cached",
                "detail": f"Cached data in use{stale_text}",
                "fetched_at": cached.get("fetched_at"),
            }
            self._update_alerts_display_area(cached.get("alerts", []), self.current_location_id, None)
            self._update_lifecycle_display(None)
            self._update_hourly_forecast_display(cached.get("hourly_forecast"), cached.get("grid_forecast"))
            self._update_daily_forecast_display(cached.get("daily_forecast"), cached.get("grid_forecast"))
            self._update_alert_map(cached.get("alerts", []))
            self._update_nws_tab()
            self._update_dashboard_summary()
            self._finish_check_cycle()
            return

        self.current_coords = None
        self.location_runtime_status[self.current_location_id] = {
            "state": "error",
            "detail": str(e),
        }
        self._update_alerts_display_area([], self.current_location_id, None)
        self._update_lifecycle_display(None)
        self._update_hourly_forecast_display(None, None)
        self._update_daily_forecast_display(None, None)
        self._update_nws_tab()
        self._update_dashboard_summary()
        self._finish_check_cycle()

    def _clear_and_set_loading_states(self):
        self.alerts_display_area.clear()
        self.alerts_display_area.addItem("Loading alerts...")
        self.lifecycle_display_area.clear()
        self.lifecycle_display_area.addItem("Loading lifecycle...")
        self._clear_layout(self.hourly_forecast_layout)
        self.hourly_forecast_layout.addWidget(QLabel("Loading..."), 0, 0)
        self._clear_layout(self.daily_forecast_layout)
        self.daily_forecast_layout.addWidget(QLabel("Loading..."), 0, 0)

    def _get_location_config(self, location_id: str) -> Dict[str, Any]:
        for location in self.locations:
            if location.get("id") == location_id:
                return normalize_location_entry(location)
        return normalize_location_entry({"name": "Unknown", "id": location_id})

    def _resolve_bool_override(self, maybe_override: Optional[bool], fallback: bool) -> bool:
        if maybe_override is None:
            return fallback
        return bool(maybe_override)

    def _update_lifecycle_display(self, lifecycle: Optional[Dict[str, Any]]) -> None:
        self.lifecycle_display_area.clear()
        if not lifecycle:
            self.lifecycle_display_area.addItem("No lifecycle changes in this cycle.")
            return

        count = 0
        for new_alert in lifecycle.get("new", [])[:8]:
            self.lifecycle_display_area.addItem(f"[NEW] {new_alert.get('title', 'Alert')}")
            count += 1
        for updated in lifecycle.get("updated", [])[:8]:
            change_summary = "; ".join(updated.get("changes", [])[:2])
            suffix = f" | {change_summary}" if change_summary else ""
            self.lifecycle_display_area.addItem(f"[UPDATED] {updated.get('title', 'Alert')}{suffix}")
            count += 1
        for expired in lifecycle.get("expired", [])[:8]:
            self.lifecycle_display_area.addItem(f"[EXPIRED] {expired.get('title', 'Alert')}")
            count += 1
        for cancelled in lifecycle.get("cancelled", [])[:8]:
            self.lifecycle_display_area.addItem(f"[CANCELLED] {cancelled.get('title', 'Alert')}")
            count += 1

        if count == 0:
            self.lifecycle_display_area.addItem("No lifecycle changes in this cycle.")

    def _record_lifecycle_events(self, location_id: str, lifecycle: Dict[str, Any]) -> None:
        location_name = self.get_location_name_by_id(location_id)
        now_text = time.strftime('%Y-%m-%d %H:%M:%S')
        for alert in lifecycle.get("new", []):
            self.alert_history_manager.add_lifecycle_event(
                {
                    "time": now_text,
                    "location_id": location_id,
                    "location": location_name,
                    "lifecycle": "issued",
                    "alert_id": alert.get("id", ""),
                    "title": alert.get("title", ""),
                    "severity": alert.get("severity", ""),
                    "change_summary": "New alert issued",
                }
            )
        for updated in lifecycle.get("updated", []):
            self.alert_history_manager.add_lifecycle_event(
                {
                    "time": now_text,
                    "location_id": location_id,
                    "location": location_name,
                    "lifecycle": "updated",
                    "alert_id": updated.get("id", ""),
                    "title": updated.get("title", ""),
                    "severity": "",
                    "change_summary": "; ".join(updated.get("changes", [])[:3]),
                }
            )
        for expired in lifecycle.get("expired", []):
            self.escalation_repeat_state.pop(expired.get("id", ""), None)
            self.alert_history_manager.add_lifecycle_event(
                {
                    "time": now_text,
                    "location_id": location_id,
                    "location": location_name,
                    "lifecycle": "expired",
                    "alert_id": expired.get("id", ""),
                    "title": expired.get("title", ""),
                    "severity": expired.get("severity", ""),
                    "change_summary": "Alert expired",
                }
            )
        for cancelled in lifecycle.get("cancelled", []):
            self.escalation_repeat_state.pop(cancelled.get("id", ""), None)
            self.alert_history_manager.add_lifecycle_event(
                {
                    "time": now_text,
                    "location_id": location_id,
                    "location": location_name,
                    "lifecycle": "cancelled",
                    "alert_id": cancelled.get("id", ""),
                    "title": cancelled.get("title", ""),
                    "severity": cancelled.get("severity", ""),
                    "change_summary": "Alert cancelled",
                }
            )

    def _dispatch_webhooks_for_location(self, location_id: str, new_alerts: List[Dict[str, Any]]) -> None:
        if not new_alerts:
            return

        location_cfg = self._get_location_config(location_id)
        if not location_cfg.get("rules", {}).get("webhook_enabled", False):
            return

        channels = {
            "generic": {
                "enabled": self.current_enable_webhook_notifications and bool(self.current_webhook_url),
                "url": self.current_webhook_url,
            },
            "discord": {
                "enabled": self.current_enable_discord_notifications and bool(self.current_discord_webhook_url),
                "url": self.current_discord_webhook_url,
            },
            "slack": {
                "enabled": self.current_enable_slack_notifications and bool(self.current_slack_webhook_url),
                "url": self.current_slack_webhook_url,
            },
        }

        if not any(cfg.get("enabled") for cfg in channels.values()):
            return

        for alert in new_alerts:
            if not alert.get("_notify_allowed", False):
                continue
            distance_miles = alert.get("distance_miles")
            if distance_miles is None and self.current_coords:
                distance_miles = distance_point_to_geometry_miles(
                    self.current_coords[0], self.current_coords[1], alert.get("geometry")
                )
            escalation = evaluate_escalation(alert, location_cfg.get("rules", {}), distance_miles, datetime.now())
            force_all_channels = bool(escalation.get("escalate") and escalation.get("force_all_channels"))
            effective_channels = channels.copy()
            if force_all_channels:
                effective_channels = {
                    name: {"enabled": bool(cfg.get("url")), "url": cfg.get("url", "")}
                    for name, cfg in channels.items()
                }

            payload = {
                "source": "PyWeatherAlert",
                "location": location_cfg.get("name"),
                "location_id": location_id,
                "title": alert.get("title"),
                "summary": alert.get("summary"),
                "severity": alert.get("severity"),
                "event": alert.get("event"),
                "updated": alert.get("updated"),
                "link": alert.get("link"),
                "distance_miles": distance_miles,
                "escalated": bool(escalation.get("escalate")),
                "escalation_reasons": escalation.get("reasons", []),
            }
            results = dispatch_notification_channels(
                self.api_client.session,
                effective_channels,
                payload,
                include_errors=True,
            )
            for channel_name, delivery in results.items():
                sent = bool(delivery.get("success"))
                error = delivery.get("error", "")
                self.delivery_health.record(channel_name, sent, error)
                if not sent:
                    self.log_to_gui(f"{channel_name.capitalize()} notification delivery failed.", level="WARNING")
        self._update_dashboard_summary()

    def _update_alert_map(self, alerts: List[Dict[str, Any]]) -> None:
        if not (QWebEngineView and self.map_view):
            return
        if not alerts:
            self.map_view.setHtml("<html><body><h3>No active polygons for current location.</h3></body></html>")
            return

        if not self.current_coords:
            return

        geojson = self.api_client.build_alert_geojson(alerts)
        lat, lon = self.current_coords
        html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>html, body, #map {{ height: 100%; margin: 0; }}</style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const map = L.map('map').setView([{lat}, {lon}], 8);
    L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 12 }}).addTo(map);
    const geojson = {json.dumps(geojson)};
    const styleBySeverity = {{
      'Extreme': {{color: '#8b0000', weight: 2}},
      'Severe': {{color: '#cc0000', weight: 2}},
      'Moderate': {{color: '#ff9900', weight: 2}},
      'Minor': {{color: '#0066cc', weight: 2}}
    }};
    const layer = L.geoJSON(geojson, {{
      style: function(feature) {{
        const s = (feature.properties && feature.properties.severity) || 'Minor';
        return styleBySeverity[s] || {{color: '#666', weight: 2}};
      }},
      onEachFeature: function(feature, lyr) {{
        const p = feature.properties || {{}};
        lyr.bindPopup(`<b>${{p.title || 'Alert'}}</b><br/>Severity: ${{p.severity || 'Unknown'}}`);
      }}
    }}).addTo(map);
    if (layer.getLayers().length > 0) {{
      map.fitBounds(layer.getBounds(), {{padding:[20,20]}});
    }}
  </script>
</body>
</html>
"""
        self.map_view.setHtml(html)

    def _build_nws_forecast_url(self, coords: Optional[Tuple[float, float]]) -> Optional[str]:
        if not coords:
            return None
        lat, lon = coords
        return f"https://forecast.weather.gov/MapClick.php?lat={lat}&lon={lon}"

    def _update_nws_tab(self) -> None:
        nws_url = self._build_nws_forecast_url(self.current_coords)
        if QWebEngineView and self.nws_view:
            if nws_url:
                self.nws_view.setUrl(QUrl(nws_url))
            else:
                self.nws_view.setHtml("<html><body><h3>Select a location to load the NWS forecast.</h3></body></html>")
            return

        if isinstance(self.nws_view, QLabel):
            if nws_url:
                self.nws_view.setText(
                    "NWS view unavailable without PySide6-WebEngine.\n\n"
                    f"Forecast URL:\n{nws_url}"
                )
            else:
                self.nws_view.setText("NWS view unavailable without PySide6-WebEngine.")

    def _update_alerts_display_area(self, alerts: List[Any], location_id: str, lifecycle: Optional[Dict[str, Any]] = None):
        self.alerts_display_area.clear()
        if not alerts:
            self.alerts_display_area.addItem(f"No active alerts for {self.get_location_name_by_id(location_id)}.")
            return

        location_cfg = self._get_location_config(location_id)
        rules = location_cfg.get("rules", default_location_rules())
        should_notify_desktop_default = self.desktop_notification_action.isChecked()
        should_play_sound_default = self.enable_sounds_action.isChecked()
        should_notify_desktop = self._resolve_bool_override(rules.get("desktop_notifications"), should_notify_desktop_default)
        should_play_sound = self._resolve_bool_override(rules.get("play_sounds"), should_play_sound_default)
        cooldown_s = int(rules.get("suppression_cooldown_seconds", 900))

        high_priority_keywords = ["tornado", "severe thunderstorm", "flash flood warning"]
        for alert in alerts:
            now = datetime.now()
            distance_miles = alert.get("distance_miles")
            if distance_miles is None and self.current_coords:
                distance_miles = distance_point_to_geometry_miles(
                    self.current_coords[0], self.current_coords[1], alert.get("geometry")
                )

            escalation = evaluate_escalation(alert, rules, distance_miles, now)
            allowed, reason = evaluate_location_rule(
                alert,
                rules,
                now,
                ignore_quiet_hours=bool(escalation.get("override_quiet_hours", False)),
            )
            if not allowed:
                self.log_to_gui(f"Suppressed by rule ({location_cfg['name']}): {alert.get('title', 'N/A')} [{reason}]", level="DEBUG")
                continue

            title = alert.get('title', 'N/A Title')
            summary = alert.get('summary', 'No summary available.')
            distance_suffix = f" ({distance_miles:.1f} mi)" if isinstance(distance_miles, (int, float)) else ""
            compact_summary = self._compact_text(summary, 110)
            item = QListWidgetItem(f"{title}{distance_suffix} | {compact_summary}")
            item.setSizeHint(QSize(item.sizeHint().width(), 30))
            item.setToolTip(f"{title}{distance_suffix}\n\n{summary}")
            dedup_meta = self.alert_dedup.classify(alert)

            is_new = self.alert_history_manager.add_alert(
                alert.get("id", "unknown-id"),
                {
                    'id': alert.get("id", "unknown-id"),
                    'link': alert.get("link", ""),
                    'time': time.strftime('%Y-%m-%d %H:%M'),
                    'type': title.split(' ')[0],
                    'location': self.get_location_name_by_id(location_id),
                    'summary': summary,
                    'title': title,
                    'severity': alert.get("severity", ""),
                    'distance_miles': round(distance_miles, 2) if isinstance(distance_miles, (int, float)) else "",
                    'thread_id': dedup_meta.get("thread_id", ""),
                }
            )

            if is_new:
                should_send, send_reason = self.alert_dedup.should_send(
                    alert,
                    cooldown_s=cooldown_s,
                    force=bool(escalation.get("escalate", False)),
                )
                alert["_notify_allowed"] = should_send
                if not should_send:
                    self.log_to_gui(f"Suppressed duplicate notification: {title} [{send_reason}]", level="DEBUG")
                    self.alerts_display_area.addItem(item)
                    continue

                item.setBackground(QColor("#ffcccc"))  # Light red for new alerts
                if should_play_sound:
                    self._play_alert_sound(title.lower(), rules, escalation.get("escalate", False))
                if should_notify_desktop:
                    self._show_desktop_notification(f"{self.get_location_name_by_id(location_id)}: {title}", summary)

                alert_title_lower = title.lower()
                if any(keyword in alert_title_lower for keyword in high_priority_keywords):
                    self.log_to_gui("High-priority alert detected. Triggering extra notifications.", level="INFO")
                    QApplication.alert(self)
                if escalation.get("escalate"):
                    self.log_to_gui(
                        f"Escalation triggered for {title}: {', '.join(escalation.get('reasons', []))}",
                        level="IMPORTANT",
                    )
                    alert_id = alert.get("id", "")
                    self.last_escalated_alert_time[alert_id] = time.time()
                    repeat_minutes = max(1, int(escalation.get("repeat_minutes", 5)))
                    self.escalation_repeat_state[alert_id] = {
                        "next_ts": time.time() + repeat_minutes * 60,
                        "repeat_minutes": repeat_minutes,
                        "title": title,
                        "location_name": self.get_location_name_by_id(location_id),
                        "location_id": location_id,
                    }
            else:
                alert["_notify_allowed"] = False

            # Color coding by alert type
            title_lower = title.lower()
            if 'warning' in title_lower:
                item.setForeground(QColor("#cc0000"))  # Red text
            elif 'watch' in title_lower:
                item.setForeground(QColor("#ff9900"))  # Orange text
            elif 'advisory' in title_lower:
                item.setForeground(QColor("#0066cc"))  # Blue text

            self.alerts_display_area.addItem(item)

    def _play_alert_sound(self, alert_text: str, rules: Optional[Dict[str, Any]] = None, escalated: bool = False):
        """Plays appropriate system sound for alert type."""
        if self.mute_action.isChecked() or not self.enable_sounds_action.isChecked():
            return
        profile_cfg = (rules or {}).get("audio_profiles", {})
        now = datetime.now()
        hour_min = now.hour * 60 + now.minute
        day_profile = profile_cfg.get("day", {"start": "07:00", "end": "22:00", "beep_count": 1})
        night_profile = profile_cfg.get("night", {"start": "22:00", "end": "07:00", "beep_count": 1})
        active_profile = day_profile

        try:
            day_start_h, day_start_m = [int(v) for v in str(day_profile.get("start", "07:00")).split(":")]
            day_end_h, day_end_m = [int(v) for v in str(day_profile.get("end", "22:00")).split(":")]
            day_start = day_start_h * 60 + day_start_m
            day_end = day_end_h * 60 + day_end_m
            if day_start <= day_end:
                in_day = day_start <= hour_min < day_end
            else:
                in_day = hour_min >= day_start or hour_min < day_end
            active_profile = day_profile if in_day else night_profile
        except (ValueError, TypeError):
            active_profile = day_profile

        beep_count = int(active_profile.get("beep_count", 1))
        if escalated:
            beep_count = int(profile_cfg.get("escalated", {}).get("beep_count", max(beep_count, 3)))

        if 'warning' in alert_text or 'watch' in alert_text or 'advisory' in alert_text:
            for _ in range(max(1, min(beep_count, 5))):
                QApplication.beep()

    def _show_desktop_notification(self, title: str, message: str):
        """Displays a desktop notification."""
        if QSystemTrayIcon.isSystemTrayAvailable() and hasattr(self, "tray_icon"):
            self.tray_icon.showMessage(title, message, self.windowIcon(), 10000)

    def _update_hourly_forecast_display(self, forecast_json: Optional[Dict[str, Any]], grid_json: Optional[Dict[str, Any]]):
        self._clear_layout(self.hourly_forecast_layout)
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            self.latest_temperature_reading = None
            self.hourly_forecast_layout.addWidget(QLabel("8-Hour forecast data unavailable."), 0, 0)
            return

        periods = forecast_json['properties']['periods'][:8]
        if periods:
            first_temp = periods[0].get('temperature', 'N/A')
            first_unit = periods[0].get('temperatureUnit', '')
            self.latest_temperature_reading = f"{first_temp} degrees {first_unit}" if first_unit else str(first_temp)
        else:
            self.latest_temperature_reading = None
        headers = ["Time", "Temp", "Feels Like", "Wind", "Gusts", "Precip", "Humidity", "Sky", "Forecast"]
        for col, header in enumerate(headers):
            header_label = self._make_compact_label(f"<b>{header}</b>")
            if col < 8:
                header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._apply_forecast_cell_style(header_label, 0, is_header=True)
            self.hourly_forecast_layout.addWidget(header_label, 0, col)

        for i, p in enumerate(periods):
            try:
                formatted_time, start_dt, end_dt = self._format_period_time(p)
                temp = f"{p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}"

                # Get feels like temp
                feels_like_value = p.get('apparentTemperature', {}).get('value')
                if feels_like_value is None:
                    feels_like_value = p.get('heatIndex', {}).get('value')
                if feels_like_value is None:
                    feels_like_value = p.get('windChill', {}).get('value')

                if feels_like_value is not None:
                    feels_like_f = self._c_to_f(feels_like_value)
                    feels_like = f"{feels_like_f}°F" if feels_like_f is not None else temp
                else:
                    feels_like = temp

                wind_speed = p.get('windSpeed', 'N/A')
                wind_dir = p.get('windDirection', '')
                wind = f"{wind_dir} {wind_speed}" if wind_dir else wind_speed

                precip = p.get('probabilityOfPrecipitation', {}).get('value', '0')
                precip = f"{precip}%" if precip is not None else "-"

                humidity = p.get('relativeHumidity', {}).get('value')
                humidity = f"{humidity}%" if humidity is not None else "N/A"

                dewpoint_c = p.get('dewpoint', {}).get('value')
                dewpoint_f_value = self._c_to_f(dewpoint_c)
                dewpoint_f = f"{dewpoint_f_value}°F" if dewpoint_f_value is not None else "N/A"

                short_fc = p.get('shortForecast', 'N/A')
                emoji = self.get_weather_emoji(short_fc)
                gust_text = "N/A"
                sky_text = "N/A"
                detail_lines = [f"Ends: {p.get('endTime', 'N/A')}", f"Dewpoint: {dewpoint_f}"]

                if start_dt and end_dt:
                    gust_text = self._format_grid_value(
                        grid_json,
                        "windGust",
                        self._grid_value_for_period(grid_json, "windGust", start_dt, end_dt, aggregate="max"),
                    )
                    sky_text = self._format_grid_value(
                        grid_json,
                        "skyCover",
                        self._grid_value_for_period(grid_json, "skyCover", start_dt, end_dt),
                    )
                    thunder_text = self._format_grid_value(
                        grid_json,
                        "probabilityOfThunder",
                        self._grid_value_for_period(grid_json, "probabilityOfThunder", start_dt, end_dt),
                    )
                    visibility_text = self._format_grid_value(
                        grid_json,
                        "visibility",
                        self._grid_value_for_period(grid_json, "visibility", start_dt, end_dt),
                    )
                    qpf_text = self._format_grid_value(
                        grid_json,
                        "quantitativePrecipitation",
                        self._grid_value_for_period(grid_json, "quantitativePrecipitation", start_dt, end_dt, aggregate="sum"),
                    )
                    detail_lines.extend(
                        [
                            f"Gusts: {gust_text}",
                            f"Sky cover: {sky_text}",
                            f"Thunder risk: {thunder_text}",
                            f"Visibility: {visibility_text}",
                            f"QPF: {qpf_text}",
                        ]
                    )

                if p.get("temperatureTrend"):
                    detail_lines.append(f"Temperature trend: {p.get('temperatureTrend')}")
                if p.get("icon"):
                    detail_lines.append(f"Icon: {p.get('icon')}")

                forecast_label = self._make_compact_label(
                    f"{emoji} {short_fc}",
                    "\n".join(detail_lines),
                )

                time_label = self._make_compact_label(formatted_time)
                temp_label = self._make_compact_label(temp)
                feels_like_label = self._make_compact_label(feels_like)
                wind_label = self._make_compact_label(wind)
                gust_label = self._make_compact_label(gust_text)
                precip_label = self._make_compact_label(precip)
                humidity_label = self._make_compact_label(humidity)
                sky_label = self._make_compact_label(sky_text)
                for compact_label in [time_label, temp_label, feels_like_label, wind_label, gust_label, precip_label, humidity_label, sky_label]:
                    compact_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    self._apply_forecast_cell_style(compact_label, i + 1)
                self._apply_forecast_cell_style(forecast_label, i + 1)
                self.hourly_forecast_layout.addWidget(time_label, i + 1, 0, alignment=Qt.AlignmentFlag.AlignTop)
                self.hourly_forecast_layout.addWidget(temp_label, i + 1, 1, alignment=Qt.AlignmentFlag.AlignTop)
                self.hourly_forecast_layout.addWidget(feels_like_label, i + 1, 2, alignment=Qt.AlignmentFlag.AlignTop)
                self.hourly_forecast_layout.addWidget(wind_label, i + 1, 3, alignment=Qt.AlignmentFlag.AlignTop)
                self.hourly_forecast_layout.addWidget(gust_label, i + 1, 4, alignment=Qt.AlignmentFlag.AlignTop)
                self.hourly_forecast_layout.addWidget(precip_label, i + 1, 5, alignment=Qt.AlignmentFlag.AlignTop)
                self.hourly_forecast_layout.addWidget(humidity_label, i + 1, 6, alignment=Qt.AlignmentFlag.AlignTop)
                self.hourly_forecast_layout.addWidget(sky_label, i + 1, 7, alignment=Qt.AlignmentFlag.AlignTop)
                self.hourly_forecast_layout.addWidget(forecast_label, i + 1, 8)
            except Exception as e:
                self.log_to_gui(f"Error formatting hourly period: {e}", level="WARNING")

    def _update_daily_forecast_display(self, forecast_json: Optional[Dict[str, Any]], grid_json: Optional[Dict[str, Any]]):
        self._clear_layout(self.daily_forecast_layout)
        if not forecast_json or 'properties' not in forecast_json or 'periods' not in forecast_json['properties']:
            self.daily_forecast_layout.addWidget(QLabel("5-Day forecast data unavailable."), 0, 0)
            return

        periods = forecast_json['properties']['periods'][:10]
        headers = ["Period", "Temp", "Wind", "Precip", "Forecast"]
        for col, header in enumerate(headers):
            header_label = self._make_compact_label(f"<b>{header}</b>")
            if col in (1, 2, 3):
                header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._apply_forecast_cell_style(header_label, 0, is_header=True)
            self.daily_forecast_layout.addWidget(header_label, 0, col)

        for i, p in enumerate(periods):
            try:
                name = p.get('name', 'N/A')
                temp = f"{p.get('temperature', 'N/A')}°{p.get('temperatureUnit', '')}"
                wind_speed = p.get('windSpeed', 'N/A')
                wind_dir = p.get('windDirection', '')
                wind = f"{wind_dir} {wind_speed}" if wind_dir else wind_speed
                precip = p.get('probabilityOfPrecipitation', {}).get('value')
                precip_text = f"{precip}%" if precip is not None else "-"
                short_fc = p.get('shortForecast', 'N/A')
                detailed_fc = p.get('detailedForecast', 'N/A')
                emoji = self.get_weather_emoji(short_fc)
                _, start_dt, end_dt = self._format_period_time(p)

                detail_bits = []
                if start_dt and end_dt:
                    detail_bits.extend(
                        [
                            f"Gst {self._format_grid_value(grid_json, 'windGust', self._grid_value_for_period(grid_json, 'windGust', start_dt, end_dt, aggregate='max'))}",
                            f"Sky {self._format_grid_value(grid_json, 'skyCover', self._grid_value_for_period(grid_json, 'skyCover', start_dt, end_dt))}",
                            f"Tstm {self._format_grid_value(grid_json, 'probabilityOfThunder', self._grid_value_for_period(grid_json, 'probabilityOfThunder', start_dt, end_dt))}",
                            f'QPF {self._format_grid_value(grid_json, "quantitativePrecipitation", self._grid_value_for_period(grid_json, "quantitativePrecipitation", start_dt, end_dt, aggregate="sum"))}',
                            f"Vis {self._format_grid_value(grid_json, 'visibility', self._grid_value_for_period(grid_json, 'visibility', start_dt, end_dt))}",
                        ]
                    )
                if p.get("temperatureTrend"):
                    detail_bits.append(f"Trend {p.get('temperatureTrend')}")
                forecast_tooltip = detailed_fc
                if detail_bits:
                    forecast_tooltip = f"{detailed_fc}\n\n" + " | ".join(detail_bits)

                name_label = self._make_compact_label(name, forecast_tooltip)
                temp_label = self._make_compact_label(temp)
                wind_label = self._make_compact_label(wind)
                precip_label = self._make_compact_label(precip_text)
                temp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                wind_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                precip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._apply_forecast_cell_style(name_label, i + 1)
                self._apply_forecast_cell_style(temp_label, i + 1)
                self._apply_forecast_cell_style(wind_label, i + 1)
                self._apply_forecast_cell_style(precip_label, i + 1)
                self.daily_forecast_layout.addWidget(name_label, i + 1, 0)
                self.daily_forecast_layout.addWidget(temp_label, i + 1, 1, alignment=Qt.AlignmentFlag.AlignTop)
                self.daily_forecast_layout.addWidget(wind_label, i + 1, 2, alignment=Qt.AlignmentFlag.AlignTop)
                self.daily_forecast_layout.addWidget(precip_label, i + 1, 3, alignment=Qt.AlignmentFlag.AlignTop)

                short_fc_label = self._make_compact_label(f"{emoji} {short_fc}", forecast_tooltip)
                self._apply_forecast_cell_style(short_fc_label, i + 1)
                self.daily_forecast_layout.addWidget(short_fc_label, i + 1, 4)
            except Exception as e:
                self.log_to_gui(f"Error formatting daily period: {e}", level="WARNING")

    def _clear_layout(self, layout: QLayout):
        if layout is None: return
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    @staticmethod
    def _c_to_f(value_c: Optional[float]) -> Optional[int]:
        if value_c is None:
            return None
        return round(value_c * 9 / 5 + 32)

    @staticmethod
    def _parse_iso_duration(duration_text: str) -> Optional[timedelta]:
        match = re.match(
            r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$",
            duration_text,
        )
        if not match:
            return None
        return timedelta(
            days=int(match.group("days") or 0),
            hours=int(match.group("hours") or 0),
            minutes=int(match.group("minutes") or 0),
            seconds=int(match.group("seconds") or 0),
        )

    def _parse_valid_time_range(self, valid_time: str) -> Optional[Tuple[datetime, datetime]]:
        if not valid_time or "/" not in valid_time:
            return None
        start_text, duration_text = valid_time.split("/", 1)
        try:
            start_dt = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
        except ValueError:
            return None
        duration = self._parse_iso_duration(duration_text)
        if duration is None:
            return None
        return start_dt, start_dt + duration

    @staticmethod
    def _overlap_seconds(
        range_start: datetime,
        range_end: datetime,
        window_start: datetime,
        window_end: datetime,
    ) -> float:
        overlap_start = max(range_start, window_start)
        overlap_end = min(range_end, window_end)
        return max((overlap_end - overlap_start).total_seconds(), 0.0)

    @staticmethod
    def _grid_layer_meta(grid_json: Optional[Dict[str, Any]], layer_name: str) -> Dict[str, Any]:
        if not grid_json:
            return {}
        return grid_json.get("properties", {}).get(layer_name, {})

    def _grid_value_for_period(
        self,
        grid_json: Optional[Dict[str, Any]],
        layer_name: str,
        start_dt: datetime,
        end_dt: datetime,
        aggregate: str = "avg",
    ) -> Optional[float]:
        layer = self._grid_layer_meta(grid_json, layer_name)
        values = layer.get("values", [])
        weighted_total = 0.0
        weighted_seconds = 0.0
        running_sum = 0.0
        found_any = False
        max_value = None

        for entry in values:
            value = entry.get("value")
            if value is None:
                continue
            time_range = self._parse_valid_time_range(entry.get("validTime", ""))
            if not time_range:
                continue
            value_start, value_end = time_range
            overlap_seconds = self._overlap_seconds(value_start, value_end, start_dt, end_dt)
            if overlap_seconds <= 0:
                continue

            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue

            found_any = True
            if aggregate == "max":
                max_value = numeric_value if max_value is None else max(max_value, numeric_value)
                continue

            if aggregate == "sum":
                source_seconds = max((value_end - value_start).total_seconds(), 1.0)
                running_sum += numeric_value * (overlap_seconds / source_seconds)
                continue

            weighted_total += numeric_value * overlap_seconds
            weighted_seconds += overlap_seconds

        if not found_any:
            return None
        if aggregate == "max":
            return max_value
        if aggregate == "sum":
            return running_sum
        return (weighted_total / weighted_seconds) if weighted_seconds else None

    def _format_grid_value(self, grid_json: Optional[Dict[str, Any]], layer_name: str, value: Optional[float]) -> str:
        if value is None:
            return "N/A"

        layer_meta = self._grid_layer_meta(grid_json, layer_name)
        unit = str(layer_meta.get("uom") or layer_meta.get("unitCode") or "")
        lower_unit = unit.lower()

        if layer_name in {"skyCover", "probabilityOfThunder"}:
            return f"{round(value)}%"

        if layer_name == "windGust":
            if "km_h-1" in lower_unit:
                value *= 0.621371
            elif "m_s-1" in lower_unit:
                value *= 2.23694
            return f"{round(value)} mph"

        if layer_name == "visibility":
            if lower_unit.endswith(":m") or lower_unit.endswith("/m") or lower_unit == "m":
                value *= 0.000621371
            return f"{value:.1f} mi"

        if layer_name in {"quantitativePrecipitation", "snowfallAmount", "iceAccumulation"}:
            if "mm" in lower_unit:
                value *= 0.0393701
            return f'{value:.2f}"'

        return f"{round(value, 1)}"

    @staticmethod
    def _format_period_time(period: Dict[str, Any]) -> Tuple[str, Optional[datetime], Optional[datetime]]:
        start_text = period.get("startTime", "")
        end_text = period.get("endTime", "")
        try:
            start_dt = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_text.replace("Z", "+00:00"))
        except ValueError:
            return "N/A", None, None

        prefix = "Day" if period.get("isDaytime") else "Night"
        label = f'{start_dt.strftime("%I %p").lstrip("0")} {prefix}'
        return label, start_dt, end_dt

    def _open_preferences_dialog(self, initial_tab: str = "General"):
        current_prefs = {
            "repeater_info": self.current_repeater_info,
            "locations": self.locations,
            "interval_key": self.current_interval_key,
            "announce_alerts": self.announce_alerts_action.isChecked(),
            "announce_time_top": self.current_announce_time_top,
            "announce_time_15": self.current_announce_time_15,
            "announce_time_30": self.current_announce_time_30,
            "announce_time_45": self.current_announce_time_45,
            "announce_temp_top": self.current_announce_temp_top,
            "announce_temp_15": self.current_announce_temp_15,
            "announce_temp_30": self.current_announce_temp_30,
            "announce_temp_45": self.current_announce_temp_45,
            "auto_refresh_content": self.auto_refresh_action.isChecked(),
            "mute_audio": self.mute_action.isChecked(),
            "enable_sounds": self.enable_sounds_action.isChecked(),
            "enable_desktop_notifications": self.desktop_notification_action.isChecked(),
            "enable_webhook_notifications": self.current_enable_webhook_notifications,
            "webhook_url": self.current_webhook_url,
            "enable_discord_notifications": self.current_enable_discord_notifications,
            "discord_webhook_url": self.current_discord_webhook_url,
            "enable_slack_notifications": self.current_enable_slack_notifications,
            "slack_webhook_url": self.current_slack_webhook_url,
            "dark_mode_enabled": self.dark_mode_action.isChecked(),
            "show_log": self.show_log_action.isChecked(),
            "show_alerts_area": self.show_alerts_area_action.isChecked(),
            "show_forecasts_area": self.show_forecasts_area_action.isChecked(),
            "log_sort_order": self.current_log_sort_order,
        }

        dialog = SettingsDialog(self, current_settings=current_prefs, initial_tab=initial_tab)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_settings_data()

            locations_changed = self.locations != new_data["locations"]
            interval_changed = self.current_interval_key != new_data["interval_key"]

            self.current_repeater_info = new_data["repeater_info"]
            self.locations = [normalize_location_entry(loc) for loc in new_data["locations"]]
            self.current_interval_key = new_data["interval_key"]
            self.current_announce_time_top = new_data["announce_time_top"]
            self.current_announce_time_15 = new_data["announce_time_15"]
            self.current_announce_time_30 = new_data["announce_time_30"]
            self.current_announce_time_45 = new_data["announce_time_45"]
            self.current_announce_temp_top = new_data["announce_temp_top"]
            self.current_announce_temp_15 = new_data["announce_temp_15"]
            self.current_announce_temp_30 = new_data["announce_temp_30"]
            self.current_announce_temp_45 = new_data["announce_temp_45"]
            self.current_enable_webhook_notifications = new_data["enable_webhook_notifications"]
            self.current_webhook_url = new_data["webhook_url"]
            self.current_enable_discord_notifications = new_data["enable_discord_notifications"]
            self.current_discord_webhook_url = new_data["discord_webhook_url"]
            self.current_enable_slack_notifications = new_data["enable_slack_notifications"]
            self.current_slack_webhook_url = new_data["slack_webhook_url"]

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

        if self._check_in_progress:
            self.log_to_gui("Skipped timed check because a previous check is still running.", level="DEBUG")
            return

        self.main_check_timer.stop()
        self.countdown_timer.stop()
        self.top_countdown_label.setText("Next Check: checking now...")

        if self.auto_refresh_action.isChecked() and QWebEngineView and self.web_view:
            self.web_view.reload()

        # Only check the currently selected location, not all of them.
        if self.current_location_id:
            self._update_location_data(self.current_location_id)
        else:
            self.log_to_gui("No active location selected. Timed check skipped.", level="WARNING")
            self._schedule_next_timed_check(immediate=False)

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
        self.scheduled_announcement_timer.stop()
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

    def _speak_message_internal(self, text: str, escalated: bool = False):
        if self.mute_action.isChecked():
            self.log_to_gui(f"Audio muted. Would have spoken: {text}", level="DEBUG")
            return
        if self.is_tts_dummy:
            self.tts_engine.say(text)
            return
        try:
            rules = self._get_location_config(self.current_location_id).get("rules", {})
            profile_cfg = rules.get("audio_profiles", {})
            now = datetime.now()
            now_min = now.hour * 60 + now.minute
            day_profile = profile_cfg.get("day", {"start": "07:00", "end": "22:00", "voice_rate": 200})
            night_profile = profile_cfg.get("night", {"start": "22:00", "end": "07:00", "voice_rate": 170})
            active_profile = day_profile
            try:
                day_start_h, day_start_m = [int(v) for v in str(day_profile.get("start", "07:00")).split(":")]
                day_end_h, day_end_m = [int(v) for v in str(day_profile.get("end", "22:00")).split(":")]
                day_start = day_start_h * 60 + day_start_m
                day_end = day_end_h * 60 + day_end_m
                if day_start <= day_end:
                    in_day = day_start <= now_min < day_end
                else:
                    in_day = now_min >= day_start or now_min < day_end
                active_profile = day_profile if in_day else night_profile
            except (ValueError, TypeError):
                active_profile = day_profile

            voice_rate = int(active_profile.get("voice_rate", 200))
            if escalated:
                voice_rate = int(profile_cfg.get("escalated", {}).get("voice_rate", max(voice_rate, 215)))
            if hasattr(self.tts_engine, "setProperty"):
                self.tts_engine.setProperty("rate", voice_rate)
            if self.tts_engine.isBusy(): self.tts_engine.stop()
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except Exception as e:
            self.log_to_gui(f"TTS error: {e}", level="ERROR")

    def _set_last_announcement_label(self):
        if hasattr(self, "last_announcement_label"):
            self.last_announcement_label.setText(f"Last Announcement: {time.strftime('%I:%M:%S %p')}")

    def _selected_time_marks(self, announce_time: bool) -> set:
        marks = set()
        if announce_time:
            if self.current_announce_time_top:
                marks.add(0)
            if self.current_announce_time_15:
                marks.add(15)
            if self.current_announce_time_30:
                marks.add(30)
            if self.current_announce_time_45:
                marks.add(45)
        else:
            if self.current_announce_temp_top:
                marks.add(0)
            if self.current_announce_temp_15:
                marks.add(15)
            if self.current_announce_temp_30:
                marks.add(30)
            if self.current_announce_temp_45:
                marks.add(45)
        return marks

    def _check_scheduled_time_and_temperature_announcements(self):
        if self.mute_action.isChecked() or not self.announce_alerts_action.isChecked():
            return

        now = datetime.now()
        minute_key = now.strftime("%Y%m%d%H%M")
        current_minute = now.minute

        phrases: List[str] = []
        time_marks = self._selected_time_marks(announce_time=True)
        if current_minute in time_marks and self._last_time_announcement_minute_key != minute_key:
            phrases.append(f"Time is {now.strftime('%I:%M %p')}.")
            self._last_time_announcement_minute_key = minute_key

        temp_marks = self._selected_time_marks(announce_time=False)
        if current_minute in temp_marks and self._last_temp_announcement_minute_key != minute_key:
            if self.latest_temperature_reading:
                phrases.append(f"Temperature is {self.latest_temperature_reading}.")
            else:
                self.log_to_gui("Scheduled temperature announcement skipped (temperature data unavailable).", level="DEBUG")
            self._last_temp_announcement_minute_key = minute_key

        if phrases:
            self._speak_message_internal(" ".join(phrases))
            self._set_last_announcement_label()
        self._process_escalation_repeats()

    def _process_escalation_repeats(self):
        if not self.escalation_repeat_state:
            return
        now_ts = time.time()
        due_ids = [aid for aid, data in self.escalation_repeat_state.items() if now_ts >= data.get("next_ts", now_ts + 1)]
        for alert_id in due_ids:
            data = self.escalation_repeat_state.get(alert_id, {})
            title = data.get("title", "Severe alert")
            location_name = data.get("location_name", "current location")
            self._speak_message_internal(
                f"Escalated weather alert remains active for {location_name}: {title}.",
                escalated=True,
            )
            self._set_last_announcement_label()
            repeat_minutes = max(1, int(data.get("repeat_minutes", 5)))
            self.escalation_repeat_state[alert_id]["next_ts"] = now_ts + repeat_minutes * 60

    def _handle_timed_announcements(self, new_alert_titles: List[str], location_id: str):
        """Handles the logic for all timed audio announcements."""
        if self.mute_action.isChecked():
            return  # Global mute is on

        if not self.announce_alerts_action.isChecked():
            return # Timed announcements are disabled

        if new_alert_titles:
            alert_text = ". ".join(new_alert_titles)
            full_message = f"New weather alerts for {self.get_location_name_by_id(location_id)}. {alert_text}"
            self._speak_message_internal(full_message)
            self._set_last_announcement_label()
        elif self.current_repeater_info:
            self._speak_message_internal(self.current_repeater_info)
            self._set_last_announcement_label()

    # --- UI Update and State Management Methods ---
    def _update_current_time_display(self):
        if hasattr(self, 'current_time_label'):
            self.current_time_label.setText(f"Current Time: {time.strftime('%I:%M:%S %p')}")

    def _update_top_status_bar_display(self):
        if hasattr(self, 'top_repeater_label'):
            self.top_repeater_label.setText(f"Announcement: {self.current_repeater_info or 'N/A'}")
        self._update_dashboard_summary()

    def _refresh_location_overview(self) -> None:
        if not hasattr(self, "location_overview_list"):
            return
        self.location_overview_list.blockSignals(True)
        self.location_overview_list.clear()
        for loc in self.locations:
            loc_id = loc.get("id", "")
            text = (
                f"{loc.get('name', 'Unknown')}  |  {self._location_summary_text(loc_id)}"
                f"  |  {self._describe_location_escalation(loc_id)}"
                f"  |  {self._describe_location_health(loc_id)}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, loc_id)
            if loc_id == self.current_location_id:
                item.setBackground(QColor("#dbeafe"))
            self.location_overview_list.addItem(item)
        self.location_overview_list.blockSignals(False)

    def _update_dashboard_summary(self) -> None:
        if not hasattr(self, "dashboard_headline"):
            return
        alerts = self.current_alerts_by_location.get(self.current_location_id, [])
        lifecycle = self.last_lifecycle_by_location.get(self.current_location_id, {})
        status = self.location_runtime_status.get(self.current_location_id, {})
        stats = self.delivery_health.stats()
        total_attempts = sum(int(data.get("attempts", 0)) for data in stats.values())
        total_failures = sum(int(data.get("failures", 0)) for data in stats.values())
        worst_alert = None
        if alerts:
            worst_alert = max(alerts, key=lambda alert: self._severity_rank(alert.get("severity", "Unknown")))

        self.dashboard_headline.setText(f"Now monitoring {self.get_current_location_name()}")
        if worst_alert:
            self.dashboard_subheadline.setText(
                f"Top risk is {worst_alert.get('title', 'active alert')} with severity "
                f"{worst_alert.get('severity', 'Unknown')}."
            )
        else:
            self.dashboard_subheadline.setText("No active alerts. Forecast, map, and delivery health remain available.")

        self.active_alerts_value_label.setText(str(len(alerts)))
        self.active_alerts_detail_label.setText(
            "No active alerts." if not alerts else
            f"Highest severity: {worst_alert.get('severity', 'Unknown')} · {len(lifecycle.get('new', []))} new this cycle"
        )

        escalation_count = self._active_escalation_count(self.current_location_id)
        self.escalations_value_label.setText(str(escalation_count))
        self.escalations_detail_label.setText(
            "No repeating escalations armed." if escalation_count == 0 else
            f"{escalation_count} escalated alert(s) still repeating."
        )

        state_value = {
            "online": "ONLINE",
            "cached": "CACHED",
            "error": "ERROR",
        }.get(status.get("state", "idle"), "IDLE")
        self.data_state_value_label.setText(state_value)
        self.data_state_detail_label.setText(self._describe_location_health(self.current_location_id))

        success_rate = 100.0 if total_attempts == 0 else ((total_attempts - total_failures) / total_attempts) * 100.0
        self.delivery_value_label.setText(f"{success_rate:.0f}%")
        self.delivery_detail_label.setText(
            "No notification traffic yet." if total_attempts == 0 else
            f"{total_failures} failed of {total_attempts} recent attempts."
        )

        self._refresh_location_overview()

    def _on_location_overview_clicked(self, item: QListWidgetItem) -> None:
        location_id = item.data(Qt.ItemDataRole.UserRole)
        index = self.location_combo.findData(location_id)
        if index != -1:
            self.location_combo.setCurrentIndex(index)

    def _apply_loaded_settings_to_ui(self):
        self.announce_alerts_action.setChecked(self.current_announce_alerts_checked)
        self.auto_refresh_action.setChecked(self.current_auto_refresh_content_checked)
        self.mute_action.setChecked(self.current_mute_audio_checked)
        self.enable_sounds_action.setChecked(self.current_enable_sounds)
        self.desktop_notification_action.setChecked(self.current_enable_desktop_notifications)
        self.dark_mode_action.setChecked(self.current_dark_mode_enabled)
        
        # Block signals to prevent toggled slots from firing during setup
        self.show_log_action.blockSignals(True)
        self.show_alerts_area_action.blockSignals(True)
        self.show_forecasts_area_action.blockSignals(True)
        self.show_monitoring_status_action.blockSignals(True)
        self.show_location_overview_action.blockSignals(True)
        self.file_show_monitoring_status_action.blockSignals(True)

        self.show_log_action.setChecked(self.current_show_log_checked)
        self.show_alerts_area_action.setChecked(self.current_show_alerts_area_checked)
        self.show_forecasts_area_action.setChecked(self.current_show_forecasts_area_checked)
        self.show_monitoring_status_action.setChecked(self.current_show_monitoring_status_checked)
        self.show_location_overview_action.setChecked(self.current_show_location_overview_checked)
        self.file_show_monitoring_status_action.setChecked(self.current_show_monitoring_status_checked)

        self.show_log_action.blockSignals(False)
        self.show_alerts_area_action.blockSignals(False)
        self.show_forecasts_area_action.blockSignals(False)
        self.show_monitoring_status_action.blockSignals(False)
        self.show_location_overview_action.blockSignals(False)
        self.file_show_monitoring_status_action.blockSignals(False)

        self._update_panel_visibility()

        self._update_location_dropdown()
        self.top_interval_combo.setCurrentText(self.current_interval_key)

        self._update_top_status_bar_display()
        self._update_web_sources_menu()
        self._apply_color_scheme()
        self._apply_log_sort()

        if QWebEngineView and self.web_view:
            self._load_web_view_url(self.current_radar_url)
        self._update_nws_tab()

        self._refresh_location_overview()
        self._update_dashboard_summary()
        self.log_to_gui("Settings applied to UI.", level="INFO")

    def _update_location_dropdown(self):
        self.location_combo.blockSignals(True)
        self.location_combo.clear()
        for loc in self.locations:
            self.location_combo.addItem(loc["name"], loc["id"])
        self.location_combo.addItem("Manage Locations...", MANAGE_LOCATIONS_VALUE)
        
        current_index = self.location_combo.findData(self.current_location_id)
        if current_index != -1:
            self.location_combo.setCurrentIndex(current_index)
        self.location_combo.blockSignals(False)

    def _update_main_timer_state(self):
        is_active = self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()
        if is_active:
            if not self.main_check_timer.isActive():
                self.log_to_gui("Timed checks starting.", level="INFO")
            if not self._check_in_progress:
                self._schedule_next_timed_check(immediate=True)
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
        is_active = self.announce_alerts_action.isChecked() or self.auto_refresh_action.isChecked()
        if not is_active:
            self.top_countdown_label.setText("Next Check: --:-- (Paused)")
        else:
            remaining = max(self.remaining_time_seconds, 0)
            minutes, seconds = divmod(remaining, 60)
            self.top_countdown_label.setText(f"Next Check: {minutes:02d}:{seconds:02d}")
            if self.remaining_time_seconds > 0:
                self.remaining_time_seconds -= 1

    def _update_panel_visibility(self):
        """Centralized function to control visibility of main UI panels."""
        show_alerts = self.show_alerts_area_action.isChecked()
        show_forecasts = self.show_forecasts_area_action.isChecked()
        show_log = self.show_log_action.isChecked()
        show_monitoring_status = self.show_monitoring_status_action.isChecked()
        show_location_overview = self.show_location_overview_action.isChecked()

        self.alerts_group.setVisible(show_alerts)
        self.combined_forecast_widget.setVisible(show_forecasts)
        self.alerts_forecasts_container.setVisible(show_alerts or show_forecasts)
        self.log_widget.setVisible(show_log)
        if hasattr(self, "dashboard_overview_panel"):
            self.dashboard_overview_panel.setVisible(show_monitoring_status)
        if hasattr(self, "location_overview_header"):
            self.location_overview_header.setVisible(show_location_overview)
        if hasattr(self, "location_overview_list"):
            self.location_overview_list.setVisible(show_location_overview)

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

    def _on_show_monitoring_status_toggled(self, checked):
        self.current_show_monitoring_status_checked = checked
        if hasattr(self, "show_monitoring_status_action") and self.show_monitoring_status_action.isChecked() != checked:
            self.show_monitoring_status_action.blockSignals(True)
            self.show_monitoring_status_action.setChecked(checked)
            self.show_monitoring_status_action.blockSignals(False)
        if hasattr(self, "file_show_monitoring_status_action") and self.file_show_monitoring_status_action.isChecked() != checked:
            self.file_show_monitoring_status_action.blockSignals(True)
            self.file_show_monitoring_status_action.setChecked(checked)
            self.file_show_monitoring_status_action.blockSignals(False)
        self._update_panel_visibility()
        self._save_settings()

    def _on_show_location_overview_toggled(self, checked):
        self.current_show_location_overview_checked = checked
        self._update_panel_visibility()
        self._save_settings()

    def _show_about_dialog(self):
        AboutDialog(self).exec()

    def _show_incident_center(self, initial_tab: Any = "Overview"):
        if isinstance(initial_tab, bool):
            initial_tab = "Overview"
        if not self.current_location_id:
            QMessageBox.information(self, "No Location", "Select a location first.")
            return
        dialog = IncidentCenterDialog(
            self.alert_history_manager,
            self.delivery_health,
            self.current_location_id,
            self.get_current_location_name(),
            self,
            initial_tab=initial_tab,
        )
        dialog.exec()

    def _show_alert_history(self):
        self._show_incident_center("Alert History")

    def _show_lifecycle_timeline(self):
        self._show_incident_center("Lifecycle")

    def _show_delivery_health(self):
        self._show_incident_center("Delivery Health")

    def _send_test_notifications(self):
        channels = {
            "generic": {
                "enabled": self.current_enable_webhook_notifications and bool(self.current_webhook_url),
                "url": self.current_webhook_url,
            },
            "discord": {
                "enabled": self.current_enable_discord_notifications and bool(self.current_discord_webhook_url),
                "url": self.current_discord_webhook_url,
            },
            "slack": {
                "enabled": self.current_enable_slack_notifications and bool(self.current_slack_webhook_url),
                "url": self.current_slack_webhook_url,
            },
        }
        if not any(cfg.get("enabled") for cfg in channels.values()):
            QMessageBox.information(self, "No Channels", "No notification channels are enabled/configured.")
            return
        payload = {
            "source": "PyWeatherAlert",
            "location": self.get_current_location_name(),
            "location_id": self.current_location_id,
            "title": "Test Notification",
            "summary": "This is a test notification from PyWeatherAlert.",
            "severity": "Test",
            "event": "System Test",
            "updated": datetime.now().isoformat(timespec="seconds"),
            "link": "",
            "escalated": False,
        }
        results = dispatch_notification_channels(self.api_client.session, channels, payload, include_errors=True)
        failures = []
        for channel_name, delivery in results.items():
            sent = bool(delivery.get("success"))
            error = delivery.get("error", "")
            self.delivery_health.record(channel_name, sent, error)
            if not sent:
                failures.append(f"{channel_name}: {error or 'failed'}")
        self._update_dashboard_summary()
        if failures:
            QMessageBox.warning(self, "Test Completed With Failures", "\n".join(failures))
        else:
            QMessageBox.information(self, "Test Successful", "All enabled channels accepted the test payload.")

    def _export_incident_report(self):
        if not self.current_location_id:
            QMessageBox.warning(self, "No Location", "No active location selected.")
            return
        alerts = self.current_alerts_by_location.get(self.current_location_id, [])
        if not alerts:
            QMessageBox.information(self, "No Alerts", "There are no current alerts to export for this location.")
            return

        location_name = self.get_current_location_name()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suggested = f"incident_{location_name.replace(' ', '_')}_{ts}"
        base_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Incident Report",
            suggested,
            "JSON Files (*.json)",
        )
        if not base_path:
            return

        if not base_path.lower().endswith(".json"):
            base_path = f"{base_path}.json"

        json_path = base_path
        csv_path = base_path[:-5] + ".csv"
        pdf_path = base_path[:-5] + ".pdf"

        timeline = self.alert_history_manager.get_recent_lifecycle(500, location_id=self.current_location_id)
        export_incident_json(json_path, location_name, alerts, timeline)
        export_incident_csv(csv_path, alerts)
        self._export_incident_pdf(pdf_path, location_name, alerts, timeline[:50])
        self.log_to_gui(f"Incident export created: {json_path}, {csv_path}, {pdf_path}", level="INFO")
        QMessageBox.information(self, "Export Complete", f"Saved incident report files:\n{json_path}\n{csv_path}\n{pdf_path}")

    def _export_incident_pdf(self, pdf_path: str, location_name: str, alerts: List[Dict[str, Any]], timeline: List[Dict[str, Any]]) -> None:
        lines = [
            f"Incident Report - {location_name}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "Active Alerts:",
        ]
        for alert in alerts[:100]:
            lines.append(
                f"- {alert.get('title', 'Alert')} | Severity: {alert.get('severity', '')} | Expires: {alert.get('expires', '')}"
            )
        lines.append("")
        lines.append("Timeline:")
        for event in timeline:
            lines.append(
                f"- {event.get('time', '')} [{event.get('lifecycle', '')}] {event.get('title', '')} {event.get('change_summary', '')}"
            )

        from PySide6.QtGui import QTextDocument, QPageSize, QPageLayout, QPdfWriter

        writer = QPdfWriter(pdf_path)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
        writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.Letter), QPageLayout.Orientation.Portrait, QMarginsF(20, 20, 20, 20)))
        doc = QTextDocument()
        doc.setPlainText("\n".join(lines))
        doc.print(writer)

    def _show_github_help(self):
        QDesktopServices.openUrl(QUrl(GITHUB_HELP_URL))

    @Slot(int)
    def _on_location_selected(self, index):
        if index == -1:
            return
        location_id = self.location_combo.itemData(index)
        if location_id == MANAGE_LOCATIONS_VALUE:
            previous_index = self.location_combo.findData(self.current_location_id)
            if previous_index != -1:
                self.location_combo.blockSignals(True)
                self.location_combo.setCurrentIndex(previous_index)
                self.location_combo.blockSignals(False)
            self._open_preferences_dialog("Locations")
            return
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
        stylesheet = DARK_STYLESHEET if self.current_dark_mode_enabled else LIGHT_STYLESHEET
        self.setStyleSheet(stylesheet)
        self.log_to_gui(f"Applied {'dark' if self.current_dark_mode_enabled else 'light'} theme.", level="INFO")

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
                settings_file = os.path.join(self._get_user_data_path(), SETTINGS_FILE_NAME)
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
                # First, validate the file is a proper JSON
                with open(file_name, 'r') as f:
                    settings_to_restore = json.load(f)

                # If valid, proceed with writing it
                settings_file = os.path.join(self._get_user_data_path(), SETTINGS_FILE_NAME)
                self.settings_manager.save(settings_to_restore)

                self.log_to_gui(f"Settings restored from {file_name}", level="INFO")
                QMessageBox.information(self, "Restore Successful", 
                                        "Settings have been restored. The application will now apply the new settings.")
                
                # Reload and reapply everything
                self._load_settings()
                self._apply_loaded_settings_to_ui()
                if self.current_location_id:
                    self._update_location_data(self.current_location_id)

            except (IOError, OSError, json.JSONDecodeError) as e:
                self.log_to_gui(f"Error restoring settings: {e}", level="ERROR")
                QMessageBox.critical(self, "Restore Error", f"Failed to restore settings from the selected file.\n\nError: {e}")

    def _filter_alerts(self):
        sender = self.sender()
        
        # Exclusive "All" button
        if sender == self.all_alerts_button and self.all_alerts_button.isChecked():
            self.warning_button.setChecked(False)
            self.watch_button.setChecked(False)
            self.advisory_button.setChecked(False)
        # If another button is clicked, uncheck "All".
        elif sender != self.all_alerts_button and self.all_alerts_button.isChecked():
            self.all_alerts_button.setChecked(False)

        # If all specific filters are unchecked, re-check "All".
        if not self.warning_button.isChecked() and \
           not self.watch_button.isChecked() and \
           not self.advisory_button.isChecked():
            self.all_alerts_button.setChecked(True)

        show_all = self.all_alerts_button.isChecked()
        show_warnings = self.warning_button.isChecked()
        show_watches = self.watch_button.isChecked()
        show_advisories = self.advisory_button.isChecked()

        for i in range(self.alerts_display_area.count()):
            item = self.alerts_display_area.item(i)
            text = item.text().lower()

            # Logic to determine if the item should be visible
            is_warning = 'warning' in text
            is_watch = 'watch' in text
            is_advisory = 'advisory' in text
            
            # Always show items that are not specific alert types (e.g., "No active alerts...")
            is_generic_message = not (is_warning or is_watch or is_advisory)

            if show_all or is_generic_message:
                item.setHidden(False)
            else:
                show = (is_warning and show_warnings) or \
                       (is_watch and show_watches) or \
                       (is_advisory and show_advisories)
                item.setHidden(not show)


# --- Application Entry Point ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create('Fusion'))
    window = WeatherAlertApp()
    window.show()
    sys.exit(app.exec())
