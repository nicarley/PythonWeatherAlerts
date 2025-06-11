# PyWeatherAlert - Weather Alert Monitor

PyWeatherAlertGui is a Python desktop application built with PySide6 that monitors weather alerts from the National Weather Service (NWS) for a specified airport ID. It provides visual and (optional) audio notifications for new alerts, displays current alerts, shows station forecasts, and allows users to view web-based weather radar or other web sources.
There is a graphical user interface, and a simple python script that allows you to put your HAM or GMRS Call sign in and nearest NWS airport ID and it will trigger the alert system inside the app.
<a href="https://github.com/nicarley/PythonWeatherAlerts/blob/master/resources/pyweather.png?raw=true">
<img src="https://github.com/nicarley/PythonWeatherAlerts/blob/master/resources/pyweather.png?raw=true" width="800px" />
</a>

## More info on PyWeatherAlertGUI:
## Features

-   **NWS Alert Monitoring**: Periodically checks for new weather alerts (warnings, watches, advisories) for a user-defined airport ID.
-   **Audio Announcements**:
    -   Optionally announces new weather alerts using text-to-speech (TTS).
    -   Optionally announces a custom repeater message after each check cycle.
-   **Visual Information**:
    -   Displays current active alerts.
    -   Shows 4-hour and 3-day station forecasts for the specified airport ID.
    -   Embedded web view to display weather radar or other user-defined web sources (supports HTML and opens PDFs externally).
    -   Top status bar displaying current Repeater, Airport ID, Check Interval, and a countdown to the next check.
-   **Customizable Web Sources**:
    -   Pre-configured with N.W.S. Radar and Windy.com.
    -   Users can add, edit, delete, and reorder their own web sources (URLs) via a dedicated submenu.
    -   Option to quickly add the currently viewed URL in the web view as a new source.
-   **Configurable Settings via Preferences Dialog**:
    -   Set Repeater Announcement text.
    -   Define the Airport ID for weather data.
    -   Choose the check interval for new alerts and content refresh (e.g., 1 minute, 15 minutes, 1 hour).
-   **Menu-Driven Interface**:
    -   **File Menu**: Access Preferences, Backup/Restore Settings, and Exit.
    -   **View Menu**: Manage Web Sources, toggle visibility of Log Panel, Alerts Area, Forecasts Area, and enable/disable Dark Mode.
    -   **Actions Menu**: Toggle "Announce Alerts & Start Timer," "Auto-Refresh Content," and manually trigger "Speak Repeater Info & Reset Timer."
    -   **Help Menu**: Access the application's help page on GitHub directly.
-   **Dark Mode**: Option to switch between a light and dark theme for the application interface.
-   **Settings Management**:
    -   All user configurations are saved to a `settings.txt` file in JSON format within a `resources` subdirectory.
    -   Backup and Restore functionality for the settings file.
-   **Logging**: Provides an in-app log panel for status messages, errors, and debug information.
-   **Styling**:
    -   Supports custom stylesheets (`modern.qss` for light mode, `dark_modern.qss` for dark mode).
    -   Attempts to use native macOS styling for light/dark mode when "Enable Dark Mode" is unchecked on macOS.

## Requirements

-   **Python 3.x**
You can typically install these Python libraries using pip:
-   **PySide6**: For the graphical user interface.
    -   `PySide6.QtWebEngineWidgets` is required for the embedded web view. If not found, the web view will be disabled.
-   **requests**: For making HTTP requests to weather APIs.
-   **feedparser**: For parsing Atom feeds from the NWS alerts.
-   **pyttsx3**: For text-to-speech functionality.

