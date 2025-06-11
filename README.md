A Python script, and GUI that allows a computer (or Raspberry Pi) to ID, and get and broadcast weather alerts. It then uses speach to broadcast the alerts over the sound card.  Simply plug in the headphone our audio output to a repeater or VOX input device.  Python scripts use import requests, feedparser, pyttsx3, time,logging,qt pyside6
Alerts come from the N.W.S. Alerts API, simply enter station ID.  It also shows latest N.W.S. Radar (currently defaults to Salem, IL where I'm from.)
Settings are stored in an XML document under "resources/settings.txt"

<a href="https://github.com/nicarley/PythonWeatherAlerts/blob/master/resources/pyweather.png?raw=true>
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

## Setup and Usage

**Run the Script**:
Configuration:•Repeater Announcement: Enter any text you want announced after weather alerts or during manual "Speak & Reset".•Airport ID: Enter the 3-letter IATA airport code (e.g., SLO, LAX, JFK). The application will automatically prefix it with "K" for NWS lookups. An "Airport ID Lookup" link is provided.•Web Source: Select a web source from the dropdown.•Add New Source...: Opens a dialog to add a custom web page or PDF URL with a display name.•Add Current View as Source...: If you've navigated to a URL in the web view, this option lets you save it with a custom name.•Manage Sources...: Opens a dialog to edit, delete, and reorder existing web sources.•Check Interval: Choose how frequently the application should check for alerts and refresh content.4.Controls:•Show Log / Show Alerts / Show Forecasts: Checkboxes to toggle the visibility of these UI panels.•Speak & Reset: Manually triggers the repeater announcement (if "Announce Alerts" is on) and resets the check timer.•Announce Alerts & Start Timer: Enables audio announcements for new alerts and the repeater message. Starts the periodic check cycle.•Auto-Refresh Content: Enables periodic refresh of the web view and station forecasts according to the check interval, even if "Announce Alerts" is off.•Backup/Restore Settings: Allows saving the current settings.txt to a custom location or restoring settings from a backup file.