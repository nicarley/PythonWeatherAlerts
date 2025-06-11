A Python script, and GUI that allows a computer (or Raspberry Pi) to ID, and get and broadcast weather alerts. It then uses speach to broadcast the alerts over the sound card.  Simply plug in the headphone our audio output to a repeater or VOX input device.  Python scripts use import requests, feedparser, pyttsx3, time,logging,qt pyside6
Alerts come from the N.W.S. Alerts API, simply enter station ID.  It also shows latest N.W.S. Radar (currently defaults to Salem, IL where I'm from.)
Settings are stored in an XML document under "resources/settings.txt"

<a href="https://github.com/nicarley/PythonWeatherAlerts/blob/master/resources/pyweather.png?raw=true">
<img src="https://github.com/nicarley/PythonWeatherAlerts/blob/master/resources/pyweather.png?raw=true" width="800px" />
</a>

# PyWeatherAlertGui - Weather Alert Monitor

**Version:** 2025.06.26 (as per `versionnumber` in the script)

PyWeatherAlertGui is a Python desktop application built with PySide6 that monitors weather alerts from the National Weather Service (NWS) for a specified airport ID. It provides visual and (optional) audio notifications for new alerts, displays current alerts, shows station forecasts, and allows users to view web-based weather radar or other web sources.

## Features

-   **NWS Alert Monitoring**: Periodically checks for new weather alerts (warnings, watches, advisories) for a user-defined airport ID.
-   **Audio Announcements**:
    -   Optionally announces new weather alerts using text-to-speech (TTS).
    -   Optionally announces a custom repeater message after each check cycle.
-   **Visual Information**:
    -   Displays current active alerts.
    -   Shows 4-hour and 3-day station forecasts for the specified airport ID.
    -   Embedded web view to display weather radar or other user-defined web sources (supports HTML and opens PDFs externally).
-   **Customizable Web Sources**:
    -   Pre-configured with N.W.S. Radar and Windy.com.
    -   Users can add, edit, delete, and reorder their own web sources (URLs).
    -   Option to quickly add the currently viewed URL in the web view as a new source.
-   **Configurable Check Interval**: Users can set how often the application checks for new alerts (e.g., 1 minute, 15 minutes, 1 hour).
-   **User Interface Controls**:
    -   Toggle visibility of the log panel, current alerts area, and station forecasts area.
    -   Manually trigger a "Speak & Reset" action to announce repeater info and reset the check timer.
    -   Option to "Auto-Refresh Content" (web view and forecasts) on the check interval without necessarily enabling audio alerts.
-   **Settings Management**:
    -   All user configurations (airport ID, repeater info, web sources, checkbox states, interval) are saved to a `settings.txt` file.
    -   Backup and Restore functionality for the settings file.
-   **Logging**: Provides an in-app log panel for status messages, errors, and debug information.
-   **Styling**: Supports a custom stylesheet (`modern.qss`) for a modern look and feel.

## Requirements

-   **Python 3.x**
-   **PySide6**: For the graphical user interface.
    -   `PySide6.QtWebEngineWidgets` is required for the embedded web view. If not found, the web view will be disabled.
-   **requests**: For making HTTP requests to weather APIs.
-   **feedparser**: For parsing Atom feeds from the NWS alerts.
-   **pyttsx3**: For text-to-speech functionality.
You can typically install these Python libraries using pip.

## Usage

* Configuration:
  * Repeater Announcement: Enter any text you want announced after weather alerts or during manual "Speak & Reset".
  * Airport ID: Enter the 3-letter IATA airport code (e.g., SLO, LAX, JFK). The application will automatically prefix it with "K" for NWS lookups. An "Airport ID Lookup" link is provided.
  * Web Source: Select a web source from the dropdown.
  * Add New Source...: Opens a dialog to add a custom web page or PDF URL with a display name.
  * Add Current View as Source...: If you've navigated to a URL in the web view, this option lets you save it with a custom name.
  * Manage Sources...: Opens a dialog to edit, delete, and reorder existing web sources.
  * Check Interval: Choose how frequently the application should check for alerts and refresh content.
* Controls:
  * Show Log / Show Alerts / Show Forecasts: Checkboxes to toggle the visibility of these UI panels.
  * Speak & Reset: Manually triggers the repeater announcement (if "Announce Alerts" is on) and resets the check timer.
  * Announce Alerts & Start Timer: Enables audio announcements for new alerts and the repeater message. Starts the periodic check cycle.
  * Auto-Refresh Content: Enables periodic refresh of the web view and station forecasts according to the check interval, even if "Announce Alerts" is off.•Backup/Restore Settings: Allows saving the current settings.txt to a custom location or restoring settings from a backup file.

## Overall Application Structure
The application is built using the PySide6 library, a Python binding for the Qt framework, which is used for creating graphical user interfaces.

Main Window (WeatherAlertApp): This is the core class that defines the main application window and orchestrates all its functionalities.
Dialogs:
AddEditSourceDialog: A dialog for users to add new web sources (like radar pages) or edit existing ones.
GetNameDialog: A simple dialog to prompt the user for a name when saving the currently viewed web page as a new source.
ManageSourcesDialog: Allows users to view, reorder, edit, and delete their saved web sources.
Helper Class (_DummyEngine): A fallback text-to-speech engine used if the primary pyttsx3 engine fails to initialize. This ensures the application can run without audio output if TTS is unavailable.
Key Functionalities
Configuration:

Repeater Announcement: Users can input a custom message that can be announced periodically.
Airport ID: The primary input for fetching weather data. The application uses this ID to get NWS alerts and forecasts.
Web Source Management: Users can select from a list of web sources (e.g., weather radar sites). They can add new URLs, edit existing ones, manage their order, and quickly save the currently viewed page.
Check Interval: Users can define how often the application checks for new weather information.
Weather Data Fetching & Display:

NWS API Integration:
Fetches station coordinates based on the airport ID.
Uses coordinates to get gridpoint properties from the NWS API, which then provide URLs for specific forecast data.
Retrieves active weather alerts (warnings, watches, advisories) as an Atom feed.
Fetches 4-hour and 3-day station forecasts.
Display Areas:
Current Alerts: Shows a list of active weather alerts for the selected location.
Station Forecasts: Displays the 4-hour and 3-day forecasts in separate text areas. These areas are designed to adjust their height based on the content.
Web View: An embedded web browser (QWebEngineView) displays the selected web source. It can handle HTML pages and will attempt to open PDF links externally using the system's default viewer.
Log Area: A text area at the bottom of the application shows status messages, errors, and debug information.
Timers and Automation:

Main Check Timer (main_check_timer): Periodically triggers the perform_check_cycle method based on the selected "Check Interval." This timer is active if either "Announce Alerts" or "Auto-Refresh Content" is enabled.
Countdown Timer (countdown_timer): Updates a label in the UI to show the time remaining until the next check.
perform_check_cycle Method: This is the heart of the automated updates. When triggered:
It reloads the current web view.
It updates the station forecasts.
If "Announce Alerts" is enabled:
It fetches and displays new alerts.
It announces new alerts via TTS.
It announces the repeater information via TTS.
User Interface Controls & Features:

Visibility Toggles: Checkboxes allow users to show or hide the "Log," "Current Alerts," and "Station Forecasts" sections.
Speak & Reset: A button to manually trigger the repeater announcement (if "Announce Alerts" is active) and immediately reset the check timer, forcing a new check cycle.
Announce Alerts & Start Timer: A checkbox to enable/disable audio announcements for alerts and the repeater message. This also controls one of the conditions for starting the main check timer.
Auto-Refresh Content: A checkbox to enable/disable periodic refreshing of the web view and forecasts, independent of audio announcements. This also contributes to starting the main check timer.
Backup & Restore Settings: Buttons to allow users to save their settings.txt to a custom location or restore settings from a previously saved backup file.
Settings Persistence:

All user-configurable settings (airport ID, repeater info, web sources, checkbox states, check interval) are saved in a JSON file named settings.txt located in a resources subdirectory.
These settings are loaded when the application starts and saved whenever a relevant setting is changed.
Text-to-Speech (TTS):

Uses the pyttsx3 library for audio announcements.
Includes a fallback mechanism (_DummyEngine) if pyttsx3 fails, logging messages instead of speaking them.
Styling and Appearance:

## Code Structure Highlights
Constants: Global constants are defined at the beginning of the script for default values, API URLs, file names, and UI text, promoting maintainability.
Dialog Classes: Each dialog (AddEditSourceDialog, GetNameDialog, ManageSourcesDialog) is a self-contained class responsible for its specific UI and logic.

WeatherAlertApp Methods:
* __init__: Initializes the main window, state variables, loads settings, and sets up the UI.
* _load_settings / _save_settings: Handle persistence of application settings.
* _init_ui: Constructs the entire user interface, creating widgets and arranging them in layouts.
* _fetch_* methods: Encapsulate the logic for making API calls to the NWS.
* _format_*_display methods: Prepare fetched data for display in the UI.
* _update_*_display_area: Methods to refresh the content of the text areas.
* _on_*_toggled / _on_*_selected: Slot methods connected to UI events (checkbox changes, combobox selections).
* _update_main_timer_state: A crucial method that centralizes the logic for starting/stopping the main application timer based on the state of "Announce Alerts" and "Auto-Refresh Content" checkboxes.
* perform_check_cycle: The core method for periodic actions.
* _speak_* methods: Handle text-to-speech output.
* if __name__ == "__main__": block:
* Initializes the QApplication.
* Handles platform-specific styling 
* Conditionally loads the custom QSS file.
* Creates and shows the main application window.