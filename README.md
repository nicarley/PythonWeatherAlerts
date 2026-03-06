# PyWeatherAlert - Weather Alert Monitor

PyWeatherAlertGui is a Python desktop application built with PySide6 that monitors weather alerts from the National Weather Service (NWS) for user-defined locations. It provides visual and (optional) audio notifications for new alerts, displays current alerts, shows station forecasts, and allows users to view weather radar or other web sources.
There is a graphical user interface, and a simple python script that allows you to put your HAM or GMRS Call sign in and nearest NWS location ID (zip) and it will trigger the alert system inside the app.
<a href="https://github.com/nicarley/PythonWeatherAlerts/blob/master/resources/pyweather.png?raw=true">
<img src="https://github.com/nicarley/PythonWeatherAlerts/blob/master/resources/pyweather.png?raw=true" width="800px" />
</a>

## More info on PyWeatherAlertGUI:
## Features

-   **NWS Alert Monitoring**: Periodically checks for new weather alerts (warnings, watches, advisories) for user-defined locations. Alerts are filtered by severity, certainty, and urgency.
-   **Enhanced Location Inputs**: Supports ZIP, airport/station ID, `lat,lon`, county/zone IDs, and basic `City,ST` lookups.
-   **Per-Location Rules & Routing**: Each location can define severity thresholds, alert type filters, quiet hours, and routing overrides for sounds/desktop/webhook notifications.
-   **Alert Lifecycle Tracking**: Detects and highlights alert lifecycle changes (new, updated, expired, cancelled) with change summaries.
-   **Map-First Alert View**: Added an embedded map tab showing active alert polygons.
-   **Notification Channels**: Optional outbound notifications for new alerts via generic webhook, Discord webhook, and Slack webhook.
-   **Lifecycle Panel**: A dedicated lifecycle list in the main UI highlights new, updated, expired, and cancelled alerts.
-   **Audio Announcements**:
    -   Optionally announces new weather alerts using text-to-speech (TTS).
    -   Optionally announces a custom repeater message after each check cycle.
-   **Visual Information**:
    -   Displays current active alerts.
    -   Shows **8-hour and 5-day** station forecasts for the specified location.
    -   Embedded web view to display weather radar or other user-defined web sources (supports HTML and opens PDFs externally).
    -   Top status bar displaying current Repeater, Location ID, Check Interval, a countdown to the next check, and the **Current Time**.
-   **Customizable Web Sources**:
    -   Pre-configured with N.W.S. Radar and Windy.com.
    -   Users can add, edit, delete, **reorder**, and quickly save the **currently viewed URL** in the web view as a new source.
    -   Option to **open the current web view in an external browser**.
-   **Configurable Settings via Preferences Dialog**:
    -   **A comprehensive dialog** allows configuration of all key application settings:
        -   Set Repeater Announcement text.
        -   Manage locations and per-location alert rules.
        -   Choose the check interval for new alerts and content refresh (e.g., 1 minute, 15 minutes, 1 hour).
        -   Toggle "Announce Alerts & Start Timer".
        -   Toggle "Auto-Refresh Web Content".
        -   Configure outbound channels (Generic Webhook, Discord Webhook, Slack Webhook).
        -   Toggle "Enable Dark Mode".
        -   Toggle visibility of Log Panel, Alerts Area, and Forecasts Area.
-   **Menu-Driven Interface**:
    -   **File Menu**: Access Preferences, Backup/Restore Settings, and Exit.
    -   **View Menu**:
        -   **Web Sources Submenu**: Select from configured web sources, **open the current web view in an external browser**, **add the current web view as a new source**, add new sources, and manage (add, edit, delete, reorder) existing sources.
        -   Toggle visibility of Log Panel, Alerts Area, Forecasts Area.
        -   Enable/disable Dark Mode.
    -   **Actions Menu**: Toggle "Announce Alerts & Start Timer," "Auto-Refresh Content," and manually trigger "Speak Repeater Info & Reset Timer."
    -   **Help Menu**: Access the application's help page on GitHub directly.
-   **Dark Mode**: Option to switch between a light and dark theme for the application interface.
-   **Settings Management**:
    -   User configurations are saved to `settings.json` in the app's writable user-data directory.
    -   Backup and Restore functionality for the settings file.
-   **Resilience Improvements**:
    -   HTTP retry/backoff and short-lived caching for location/forecast requests.
    -   Last-known-data fallback when APIs are temporarily unavailable.
-   **Data Storage Upgrade**:
    -   Alert history is stored in JSON (`alert_history.json`) with automatic migration from legacy pickle history files (`.dat`/`.pickle`).
-   **Project Structure and Quality**:
    -   Core logic is split into modular services under `weather_alert/` (API, settings, history, rules, webhook).
    -   Unit tests are included under `tests/` with a GitHub Actions CI workflow.
-   **Logging**: Provides an in-app log panel for status messages, errors, and debug information.
-   **Styling**:
    -   Supports custom stylesheets (`modern.qss` for light mode, `dark_modern.qss` for dark mode).

## Requirements

-   **Python 3.x**
You can typically install these Python libraries using pip:
-   **PySide6**: For the graphical user interface.
    -   `PySide6.QtWebEngineWidgets` is required for the embedded web view. If not found, the web view will be disabled.
-   **requests**: For making HTTP requests to weather APIs.
-   **feedparser**: For parsing Atom feeds from the NWS alerts.
-   **pyttsx3**: For text-to-speech functionality.
-   **pgeocode**: For converting US zip codes to geographic coordinates (works offline).
-   **pandas**: A dependency of `pgeocode`.
-   **pytest** (optional): For running the unit tests in `tests/`.
