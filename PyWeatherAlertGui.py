import requests
import feedparser
import pyttsx3
import time
import logging
import tkinter as tk
from tkinter import scrolledtext, messagebox
from threading import Thread  # For potentially non-blocking speech in the future

# --- Configuration ---
# ZIP_CODE is still here but not used in the new URL (can be removed if not planned for future use)
# ZIP_CODE = "62881"
CHECK_INTERVAL_MS = 900 * 1000  # Check every 15 minutes (in milliseconds for tkinter.after)
WEATHER_ALERT_URL = "https://api.weather.gov/alerts/active.atom?point=38.6317%2C-88.9416&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Future%2CExpected"
REPEATER_INFO = "Repeater, WSDR538 Salem 462.550Mhz"

# --- Logging Setup ---
# We'll also log to the GUI, but console logging is still useful
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class WeatherAlertApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Weather Alert Monitor")
        self.root.geometry("700x500")

        self.seen_alert_ids = set()
        self.tts_engine = self._initialize_tts_engine()
        self.is_tts_dummy = isinstance(self.tts_engine, self._DummyEngine)

        # --- GUI Elements ---
        self.log_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=20, width=80)
        self.log_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.log_area.configure(state='disabled')  # Make it read-only initially

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

        self.log_to_gui(f"Monitoring weather alerts from {WEATHER_ALERT_URL}", level="INFO")
        if REPEATER_INFO:
            self.log_to_gui(f"Repeater line to be spoken each cycle: '{REPEATER_INFO}'", level="INFO")

        # Handle window close event
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Start the first check
        self.root.after(1000, self.perform_check_cycle)  # Start first check after 1 second

    def _initialize_tts_engine(self):
        """Initializes and returns the TTS engine. Returns a dummy if fails."""
        try:
            engine = pyttsx3.init()
            if engine is None:
                raise RuntimeError("pyttsx3.init() returned None")
            # Test the engine briefly
            # engine.say("TTS Engine Ready")
            # engine.runAndWait()
            logging.info("TTS engine initialized successfully by app.")
            return engine
        except Exception as e:
            logging.error(f"App: Failed to initialize TTS engine: {e}. Text-to-speech will use a fallback.")
            return self._DummyEngine()

    class _DummyEngine:
        """Fallback TTS engine that logs instead of speaking."""

        def say(self, text, name=None):
            logging.info(f"TTS (Fallback): {text}")

        def runAndWait(self):
            pass

        def stop(self):
            pass

        def isBusy(self):
            return False

        def getProperty(self, name):
            return None

        def setProperty(self, name, value):
            pass

    def log_to_gui(self, message, level="INFO"):
        """Appends a message to the GUI log area and console log."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}\n"

        self.log_area.configure(state='normal')
        self.log_area.insert(tk.END, formatted_message)
        self.log_area.see(tk.END)  # Scroll to the end
        self.log_area.configure(state='disabled')

        # Also log to console using standard logging
        if level == "ERROR":
            logging.error(message)
        elif level == "WARNING":
            logging.warning(message)
        else:
            logging.info(message)  # Default to INFO for GUI messages if not specified

    def update_status(self, message):
        self.status_var.set(message)

    def _get_alerts(self):
        """Fetches weather alerts from the configured URL."""
        url = WEATHER_ALERT_URL
        self.log_to_gui(f"Fetching alerts from {url}...", level="DEBUG")
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            self.log_to_gui(f"Successfully fetched {len(feed.entries)} entries.", level="DEBUG")
            return feed.entries
        except requests.exceptions.Timeout:
            self.log_to_gui(f"Timeout while trying to fetch alerts from {url}", level="ERROR")
        except requests.exceptions.HTTPError as http_err:
            status_code_info = f"Status code: {http_err.response.status_code}" if http_err.response else "Status code: N/A"
            self.log_to_gui(f"HTTP error occurred: {http_err} - {status_code_info}", level="ERROR")
        except requests.exceptions.RequestException as e:
            self.log_to_gui(f"Error fetching alerts from {url}: {e}", level="ERROR")
        except Exception as e:
            self.log_to_gui(f"An unexpected error occurred in _get_alerts: {e}", level="ERROR")
        return []

    def _speak_message_internal(self, text_to_speak, log_prefix="Spoken"):
        """Internal method to handle speaking and logging."""
        if not text_to_speak:
            return
        try:
            # This will make the GUI unresponsive during speech.
            # For long speech or frequent speech, threading this part would be better.
            self.tts_engine.say(text_to_speak)
            self.tts_engine.runAndWait()
            self.log_to_gui(f"{log_prefix}: {text_to_speak}", level="INFO")
        except Exception as e:
            self.log_to_gui(f"Error during text-to-speech for '{text_to_speak}': {e}", level="ERROR")

    def _speak_weather_alert(self, alert_title, alert_summary, additional_info=""):
        """Constructs and speaks the weather alert message."""
        message = f"Weather Alert: {alert_title}. Details: {alert_summary}"
        if additional_info:
            if message and not message.endswith(('.', '!', '?')):
                message += "."
            message += f" {additional_info}"
        self._speak_message_internal(message, log_prefix="Spoken Alert")

    def _speak_repeater_info(self):
        """Speaks the repeater information line."""
        if REPEATER_INFO:
            self._speak_message_internal(REPEATER_INFO, log_prefix="Spoken")

    def perform_check_cycle(self):
        """Performs one cycle of checking alerts and speaking."""
        self.log_to_gui("Starting new check cycle...", level="INFO")
        self.update_status(f"Checking for alerts... Last check: {time.strftime('%H:%M:%S')}")

        alerts = self._get_alerts()
        new_alerts_found_this_cycle = False

        if alerts:
            for alert in alerts:
                if not hasattr(alert, 'id') or not hasattr(alert, 'title') or not hasattr(alert, 'summary'):
                    self.log_to_gui(f"Skipping malformed alert entry: {alert}", level="WARNING")
                    continue

                if alert.id not in self.seen_alert_ids:
                    new_alerts_found_this_cycle = True
                    self.log_to_gui(f"New Weather Alert: {alert.title}", level="IMPORTANT")  # Custom level for GUI
                    # The console print is redundant if log_to_gui also logs to console
                    # print(f"New Weather Alert: {alert.title}")
                    self._speak_weather_alert(alert.title, alert.summary, REPEATER_INFO)
                    self.seen_alert_ids.add(alert.id)

        if not new_alerts_found_this_cycle:
            self.log_to_gui(f"No new alerts in this cycle. Total unique alerts seen: {len(self.seen_alert_ids)}.",
                            level="INFO")

        # Speak the repeater information at the end of every cycle
        self._speak_repeater_info()

        self.update_status(
            f"Check complete. Next check in ~{CHECK_INTERVAL_MS // 60000} mins. Last check: {time.strftime('%H:%M:%S')}")
        self.log_to_gui(f"Waiting for {CHECK_INTERVAL_MS // 1000} seconds before next check.", level="INFO")

        # Schedule the next check
        self.root.after(CHECK_INTERVAL_MS, self.perform_check_cycle)

    def _on_closing(self):
        """Handles graceful shutdown when the window is closed."""
        if messagebox.askokcancel("Quit", "Do you want to quit Weather Alert Monitor?"):
            self.log_to_gui("Shutting down weather alert monitor...", level="INFO")
            if hasattr(self.tts_engine, 'stop') and not self.is_tts_dummy:
                try:
                    # If the engine is busy, stop might be necessary.
                    # However, runAndWait should complete before this point in normal operation.
                    if self.tts_engine.isBusy():
                        self.tts_engine.stop()
                except Exception as e:
                    logging.error(f"Error stopping TTS engine: {e}")  # Log directly, GUI might be closing

            # It's good practice to explicitly destroy the root window.
            # This also helps in stopping the `after` loop.
            self.root.destroy()
        # else: user cancelled quit, do nothing.


if __name__ == "__main__":
    root = tk.Tk()
    app = WeatherAlertApp(root)
    root.mainloop()