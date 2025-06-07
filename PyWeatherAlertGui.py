import requests
import feedparser
import pyttsx3
import time
import logging
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk  # ttk is already imported
from threading import Thread

# --- Configuration ---
INITIAL_CHECK_INTERVAL_MS = 900 * 1000  # Default: 15 minutes

CHECK_INTERVAL_OPTIONS = {
    "1 Minute": 1 * 60 * 1000,
    "5 Minutes": 5 * 60 * 1000,
    "10 Minutes": 10 * 60 * 1000,
    "15 Minutes": 15 * 60 * 1000,
    "30 Minutes": 30 * 60 * 1000,
    "1 Hour": 60 * 60 * 1000,
}
DEFAULT_INTERVAL_KEY = "15 Minutes"  # Should match a key in CHECK_INTERVAL_OPTIONS

# Default values for URL construction and repeater info
DEFAULT_LATITUDE = "38.6317"
DEFAULT_LONGITUDE = "-88.9416"
WEATHER_URL_PREFIX = "https://api.weather.gov/alerts/active.atom?point="
WEATHER_URL_SUFFIX = "&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Future%2CExpected"
INITIAL_REPEATER_INFO = "Repeater, W S D R 5 3 8 Salem 550 Repeater"

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class WeatherAlertApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Weather Alert Monitor")
        self.root.geometry("700x650")  # Adjusted height for new elements

        self.seen_alert_ids = set()
        self.tts_engine = self._initialize_tts_engine()
        self.is_tts_dummy = isinstance(self.tts_engine, self._DummyEngine)

        self.current_check_interval_ms = CHECK_INTERVAL_OPTIONS.get(DEFAULT_INTERVAL_KEY, INITIAL_CHECK_INTERVAL_MS)
        self.after_id = None  # For the main check cycle timer
        self.countdown_after_id = None  # For the countdown display timer
        self.remaining_time_seconds = 0

        # --- Configuration Frame ---
        config_frame = tk.Frame(root, padx=5, pady=5)
        config_frame.pack(padx=10, pady=(10, 0), fill=tk.X)

        tk.Label(config_frame, text="Repeater Info:").grid(row=0, column=0, padx=(0, 5), pady=2, sticky=tk.W)
        self.repeater_info_var = tk.StringVar(value=INITIAL_REPEATER_INFO)
        self.repeater_entry = tk.Entry(config_frame, textvariable=self.repeater_info_var, width=60)
        self.repeater_entry.grid(row=0, column=1, columnspan=3, padx=5, pady=2, sticky=tk.EW)

        tk.Label(config_frame, text="Latitude:").grid(row=1, column=0, padx=(0, 5), pady=2, sticky=tk.W)
        self.latitude_var = tk.StringVar(value=DEFAULT_LATITUDE)
        self.lat_entry = tk.Entry(config_frame, textvariable=self.latitude_var, width=15)
        self.lat_entry.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)

        tk.Label(config_frame, text="Longitude:").grid(row=1, column=2, padx=(10, 5), pady=2, sticky=tk.W)
        self.longitude_var = tk.StringVar(value=DEFAULT_LONGITUDE)
        self.lon_entry = tk.Entry(config_frame, textvariable=self.longitude_var, width=15)
        self.lon_entry.grid(row=1, column=3, padx=5, pady=2, sticky=tk.W)

        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(3, weight=1)

        # --- Controls Frame ---
        controls_frame = tk.Frame(root)
        controls_frame.pack(padx=10, pady=(5, 0), fill=tk.X)

        self.speak_reset_button = tk.Button(
            controls_frame,
            text="Speak Repeater Info & Reset Timer",
            command=self._on_speak_and_reset_button_press
        )
        self.speak_reset_button.pack(side=tk.LEFT, pady=5, padx=(0, 10))

        tk.Label(controls_frame, text="Check Interval:").pack(side=tk.LEFT, pady=5, padx=(10, 5))
        self.interval_var = tk.StringVar(value=DEFAULT_INTERVAL_KEY)
        self.interval_combobox = ttk.Combobox(
            controls_frame,
            textvariable=self.interval_var,
            values=list(CHECK_INTERVAL_OPTIONS.keys()),
            state="readonly",
            width=12
        )
        self.interval_combobox.pack(side=tk.LEFT, pady=5)
        self.interval_combobox.bind("<<ComboboxSelected>>", self._on_interval_selected)

        # --- Countdown Display ---
        self.countdown_label_var = tk.StringVar(value="Next check in: --:--")
        countdown_display_label = tk.Label(controls_frame, textvariable=self.countdown_label_var, font=("Arial", 10))
        countdown_display_label.pack(side=tk.RIGHT, pady=5, padx=10)

        # --- GUI Elements (Log Area & Status Bar) ---
        self.log_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=20, width=80)
        self.log_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.log_area.configure(state='disabled')

        self.status_var = tk.StringVar()
        self.status_label = tk.Label(root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
        self.update_status("Application started. Waiting for the first check...")

        if self.is_tts_dummy:
            self.log_to_gui(
                "TTS engine failed to initialize. Using fallback (logging to console/GUI instead of speaking).",
                level="ERROR")
        else:
            self.log_to_gui("TTS engine initialized successfully.", level="INFO")

        initial_url = self._get_current_weather_url(log_errors=False)
        self.log_to_gui(
            f"Monitoring weather alerts. Initial URL will use Lat: {self.latitude_var.get()}, Lon: {self.longitude_var.get()}",
            level="INFO")
        self.log_to_gui(f"Initial repeater line: '{self.repeater_info_var.get()}'", level="INFO")
        self.log_to_gui(f"Initial check interval: {self.current_check_interval_ms // 60000} minutes.", level="INFO")

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Start the first check cycle and the countdown
        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)
        self.after_id = self.root.after(1000, self.perform_check_cycle)  # Start first check slightly delayed

    def _initialize_tts_engine(self):
        """Initializes and returns the TTS engine. Returns a dummy if fails."""
        try:
            engine = pyttsx3.init()
            if engine is None:
                raise RuntimeError("pyttsx3.init() returned None")
            logging.info("TTS engine initialized successfully by app.")
            return engine
        except Exception as e:
            logging.error(f"App: Failed to initialize TTS engine: {e}. Text-to-speech will use a fallback.")
            return self._DummyEngine()

    class _DummyEngine:
        """Fallback TTS engine that logs instead of speaking."""

        def say(self, text, name=None): logging.info(f"TTS (Fallback): {text}")

        def runAndWait(self): pass

        def stop(self): pass

        def isBusy(self): return False

        def getProperty(self, name): return None

        def setProperty(self, name, value): pass

    def log_to_gui(self, message, level="INFO"):
        """Appends a message to the GUI log area (newest at the top) and console log."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}\n"

        self.log_area.configure(state='normal')
        self.log_area.insert("1.0", formatted_message)
        self.log_area.see("1.0")
        self.log_area.configure(state='disabled')

        if level == "ERROR":
            logging.error(message)
        elif level == "WARNING":
            logging.warning(message)
        elif level == "DEBUG":
            logging.debug(message)
        else:
            logging.info(message)

    def update_status(self, message):
        self.status_var.set(message)

    def _format_time(self, total_seconds):
        """Formats total seconds into MM:SS or HH:MM:SS string."""
        if total_seconds < 0: total_seconds = 0
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _start_countdown_updater(self):
        """Updates the countdown label every second."""
        if self.countdown_after_id:  # Clear previous if any (shouldn't be necessary if managed well)
            self.root.after_cancel(self.countdown_after_id)

        if self.remaining_time_seconds > 0:
            self.remaining_time_seconds -= 1

        self.countdown_label_var.set(f"Next check in: {self._format_time(self.remaining_time_seconds)}")

        if self.remaining_time_seconds > 0:  # Continue countdown if time remains
            self.countdown_after_id = self.root.after(1000, self._start_countdown_updater)
        # else: countdown will be reset by the next check cycle or manual reset

    def _reset_and_start_countdown(self, total_seconds_for_interval):
        """Resets the countdown timer to the new interval and starts updating the display."""
        if self.countdown_after_id:
            self.root.after_cancel(self.countdown_after_id)
            self.countdown_after_id = None

        self.remaining_time_seconds = total_seconds_for_interval
        self.countdown_label_var.set(
            f"Next check in: {self._format_time(self.remaining_time_seconds)}")  # Initial display
        self._start_countdown_updater()  # Start the 1-second tick

    def _on_interval_selected(self, event=None):
        """Handles selection change in the interval Combobox."""
        selected_key = self.interval_var.get()
        new_interval_ms = CHECK_INTERVAL_OPTIONS.get(selected_key)

        if new_interval_ms is None:
            self.log_to_gui(f"Invalid interval key selected: {selected_key}. Reverting to default.", level="ERROR")
            # Optionally revert to a default or the previous valid interval
            # For now, we'll just log and not change if key is somehow invalid
            return

        if new_interval_ms == self.current_check_interval_ms:
            self.log_to_gui(f"Interval '{selected_key}' is already active.", level="DEBUG")
            return  # No change needed

        self.current_check_interval_ms = new_interval_ms
        self.log_to_gui(
            f"Check interval changed to: {selected_key} ({self.current_check_interval_ms // 60000} minutes).",
            level="INFO")

        # Cancel existing main check timer
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.log_to_gui(f"Cancelled previous main timer (ID: {self.after_id}) due to interval change.",
                            level="DEBUG")
            self.after_id = None

        # Reset and start countdown for the new interval
        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)

        # Schedule the perform_check_cycle to run *immediately* to reflect the change,
        # then it will schedule itself with the new interval.
        # Or, schedule it after the new interval. Let's schedule it immediately for responsiveness.
        self.log_to_gui("Performing an immediate check due to interval change.", level="INFO")
        self.after_id = self.root.after(100, self.perform_check_cycle)  # Small delay to allow GUI to update

        self.update_status(
            f"Interval set to {selected_key}. Next check in ~{self.current_check_interval_ms // 60000} mins.")

    def _get_current_weather_url(self, log_errors=True):
        """Constructs the weather alert URL from GUI inputs, with validation."""
        lat_str = self.latitude_var.get()
        lon_str = self.longitude_var.get()
        current_lat, current_lon = None, None

        try:
            current_lat = float(lat_str)
            if not (-90 <= current_lat <= 90):
                if log_errors:
                    self.log_to_gui(
                        f"Invalid latitude: {lat_str}. Must be between -90 and 90. Using default: {DEFAULT_LATITUDE}",
                        level="ERROR")
                    self.update_status(f"Error: Invalid latitude '{lat_str}'. Using default.")
                current_lat = float(DEFAULT_LATITUDE)
        except ValueError:
            if log_errors:
                self.log_to_gui(f"Latitude '{lat_str}' is not a valid number. Using default: {DEFAULT_LATITUDE}",
                                level="ERROR")
                self.update_status(f"Error: Invalid latitude '{lat_str}'. Using default.")
            current_lat = float(DEFAULT_LATITUDE)

        try:
            current_lon = float(lon_str)
            if not (-180 <= current_lon <= 180):
                if log_errors:
                    self.log_to_gui(
                        f"Invalid longitude: {lon_str}. Must be between -180 and 180. Using default: {DEFAULT_LONGITUDE}",
                        level="ERROR")
                    self.update_status(f"Error: Invalid longitude '{lon_str}'. Using default.")
                current_lon = float(DEFAULT_LONGITUDE)
        except ValueError:
            if log_errors:
                self.log_to_gui(f"Longitude '{lon_str}' is not a valid number. Using default: {DEFAULT_LONGITUDE}",
                                level="ERROR")
                self.update_status(f"Error: Invalid longitude '{lon_str}'. Using default.")
            current_lon = float(DEFAULT_LONGITUDE)

        return f"{WEATHER_URL_PREFIX}{current_lat}%2C{current_lon}{WEATHER_URL_SUFFIX}"

    def _get_alerts(self, url):
        """Fetches weather alerts from the provided URL."""
        self.log_to_gui(f"Fetching alerts from {url}...", level="DEBUG")
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            self.log_to_gui(f"Successfully fetched {len(feed.entries)} entries from {url}.", level="DEBUG")
            return feed.entries
        except requests.exceptions.Timeout:
            self.log_to_gui(f"Timeout while trying to fetch alerts from {url}", level="ERROR")
        except requests.exceptions.HTTPError as http_err:
            status_code_info = f"Status code: {http_err.response.status_code}" if http_err.response else "Status code: N/A"
            self.log_to_gui(f"HTTP error occurred for {url}: {http_err} - {status_code_info}", level="ERROR")
        except requests.exceptions.RequestException as e:
            self.log_to_gui(f"Error fetching alerts from {url}: {e}", level="ERROR")
        except Exception as e:
            self.log_to_gui(f"An unexpected error occurred in _get_alerts ({url}): {e}", level="ERROR")
        return []

    def _speak_message_internal(self, text_to_speak, log_prefix="Spoken"):
        """Internal method to handle speaking and logging."""
        if not text_to_speak:
            return
        try:
            self.tts_engine.say(text_to_speak)
            self.tts_engine.runAndWait()
            self.log_to_gui(f"{log_prefix}: {text_to_speak}", level="INFO")
        except Exception as e:
            self.log_to_gui(f"Error during text-to-speech for '{text_to_speak}': {e}", level="ERROR")

    def _speak_weather_alert(self, alert_title, alert_summary):
        """Constructs and speaks the weather alert message, including current repeater info."""
        repeater_info = self.repeater_info_var.get()
        message = f"Weather Alert: {alert_title}. Details: {alert_summary}"
        if repeater_info:
            if message and not message.endswith(('.', '!', '?')):
                message += "."
            message += f" {repeater_info}"
        self._speak_message_internal(message, log_prefix="Spoken Alert")

    def _speak_repeater_info(self):
        """Speaks the repeater information line from the GUI input."""
        repeater_text = self.repeater_info_var.get()
        if repeater_text:
            self._speak_message_internal(repeater_text, log_prefix="Spoken")

    def _on_speak_and_reset_button_press(self):
        """Handles the 'Speak Repeater Info & Reset Timer' button press."""
        self.log_to_gui("Speak & Reset Timer button pressed.", level="INFO")

        self._speak_repeater_info()

        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.log_to_gui(f"Cancelled previous main timer (ID: {self.after_id}).", level="DEBUG")
            self.after_id = None

        self.log_to_gui(f"Resetting timer. Next check in {self.current_check_interval_ms // 60000} minutes.",
                        level="INFO")

        # Reset countdown for the current interval
        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)

        # Schedule the next perform_check_cycle using the current interval
        # Perform check almost immediately after button press for responsiveness
        self.after_id = self.root.after(100, self.perform_check_cycle)  # Small delay

        self.update_status(
            f"Manual speak & reset. Next check in ~{self.current_check_interval_ms // 60000} mins. Last check: {time.strftime('%H:%M:%S')}")

    def perform_check_cycle(self):
        """Performs one cycle of checking alerts and speaking."""
        # Reset countdown at the beginning of each cycle
        self._reset_and_start_countdown(self.current_check_interval_ms // 1000)

        current_weather_url = self._get_current_weather_url()

        self.log_to_gui(f"Starting new check cycle for Lat: {self.latitude_var.get()}, Lon: {self.longitude_var.get()}",
                        level="INFO")
        self.update_status(f"Checking for alerts... Last check: {time.strftime('%H:%M:%S')}")

        alerts = self._get_alerts(current_weather_url)
        new_alerts_found_this_cycle = False

        if alerts:
            for alert in alerts:
                if not hasattr(alert, 'id') or not hasattr(alert, 'title') or not hasattr(alert, 'summary'):
                    self.log_to_gui(f"Skipping malformed alert entry: {alert}", level="WARNING")
                    continue

                if alert.id not in self.seen_alert_ids:
                    new_alerts_found_this_cycle = True
                    self.log_to_gui(f"New Weather Alert: {alert.title}", level="IMPORTANT")
                    self._speak_weather_alert(alert.title, alert.summary)
                    self.seen_alert_ids.add(alert.id)

        if not new_alerts_found_this_cycle:
            self.log_to_gui(f"No new alerts in this cycle. Total unique alerts seen: {len(self.seen_alert_ids)}.",
                            level="INFO")

        self._speak_repeater_info()

        self.update_status(
            f"Check complete. Next check in ~{self.current_check_interval_ms // 60000} mins. Last check: {time.strftime('%H:%M:%S')}")
        self.log_to_gui(f"Waiting for {self.current_check_interval_ms // 1000} seconds before next check.",
                        level="INFO")

        # Schedule the next check using the current interval and store its ID
        self.after_id = self.root.after(self.current_check_interval_ms, self.perform_check_cycle)

    def _on_closing(self):
        """Handles graceful shutdown when the window is closed."""
        if messagebox.askokcancel("Quit", "Do you want to quit Weather Alert Monitor?"):
            self.log_to_gui("Shutting down weather alert monitor...", level="INFO")

            if self.after_id:
                self.root.after_cancel(self.after_id)
                self.log_to_gui(f"Cancelled main check timer (ID: {self.after_id}) on exit.", level="DEBUG")
            if self.countdown_after_id:
                self.root.after_cancel(self.countdown_after_id)
                self.log_to_gui(f"Cancelled countdown timer (ID: {self.countdown_after_id}) on exit.", level="DEBUG")

            if hasattr(self.tts_engine, 'stop') and not self.is_tts_dummy:
                try:
                    if self.tts_engine.isBusy():
                        self.tts_engine.stop()
                except Exception as e:
                    logging.error(f"Error stopping TTS engine: {e}")
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = WeatherAlertApp(root)
    root.mainloop()