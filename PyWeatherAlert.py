import requests
import feedparser
import pyttsx3
import time
import logging
# import datetime # <-- No longer needed if using fixed CHECK_INTERVAL

# --- Configuration ---
# ZIP_CODE is still here but not used in the new URL
ZIP_CODE = "62881"
CHECK_INTERVAL = 900  # Check every 15 minutes (in seconds)
# Updated URL to use the point-based Atom feed
WEATHER_ALERT_URL_TEMPLATE = "https://api.weather.gov/alerts/active.atom?point=38.6317%2C-88.9416&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Future%2CExpected"
# Define the repeater information as a constant
REPEATER_INFO = "Repeater, WSDR538 Salem 462.550Mhz"

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Functions ---
def initialize_tts_engine():
    """Initializes and returns the TTS engine. Returns a dummy if fails."""
    try:
        engine = pyttsx3.init()
        if engine is None:  # Some implementations might return None on failure
            raise RuntimeError("pyttsx3.init() returned None")
        logging.info("TTS engine initialized successfully.")
        return engine
    except Exception as e:
        logging.error(f"Failed to initialize TTS engine: {e}. Text-to-speech will use a fallback.")

        class DummyEngine:
            def say(self, text, name=None):
                logging.info(f"TTS (Fallback): {text}")

            def runAndWait(self): pass

            def stop(self): pass

            def isBusy(self): return False

            def getProperty(self, name): return None

            def setProperty(self, name, value): pass

        return DummyEngine()


# Modified get_alerts function - no longer needs zip_code parameter
def get_alerts():
    """Fetches weather alerts from the configured URL."""
    url = WEATHER_ALERT_URL_TEMPLATE # Use the template directly
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        return feed.entries
    except requests.exceptions.Timeout:
        logging.error(f"Timeout while trying to fetch alerts from {url}")
    except requests.exceptions.HTTPError as http_err:
        logging.error(
            f"HTTP error occurred: {http_err} - Status code: {response.status_code if 'response' in locals() else 'N/A'}")
    except requests.exceptions.RequestException as e:
        # Modified log message as zip_code is not used in the function anymore
        logging.error(f"Error fetching alerts from {url}: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred in get_alerts: {e}")
    return []


def speak_weather_alert(engine, alert_title, alert_summary, additional_info=""):
    """Constructs and speaks the weather alert message."""
    message = f"Weather Alert: {alert_title}. Details: {alert_summary}"
    if additional_info:
        if message and not message.endswith(('.', '!', '?')):
            message += "."
        message += f" {additional_info}"
    try:
        engine.say(message)
        engine.runAndWait()
    except Exception as e:
        logging.error(f"Error during text-to-speech: {e}")


# Function to speak any generic message (kept from previous version)
def speak_message(engine, message_text):
    """Speaks a given message using the TTS engine."""
    if not message_text:  # Avoid trying to speak an empty string
        logging.debug("speak_message called with empty text, skipping.")
        return
    try:
        engine.say(message_text)
        engine.runAndWait()
        logging.info(f"Spoken: {message_text}")  # Log what was spoken
    except Exception as e:
        logging.error(f"Error during text-to-speech for message '{message_text}': {e}")


def main():
    seen_alert_ids = set()
    tts_engine = initialize_tts_engine()

    # Updated logging message to reflect monitoring a point, not a zip code
    logging.info(f"Monitoring weather alerts from {WEATHER_ALERT_URL_TEMPLATE} every {CHECK_INTERVAL} seconds.")
    if REPEATER_INFO:
        logging.info(f"Repeater line to be spoken each cycle: '{REPEATER_INFO}'")

    try:
        while True:
            # Call get_alerts without the zip_code parameter
            alerts = get_alerts()
            new_alerts_found_this_cycle = False

            if alerts:
                for alert in alerts:
                    # The alert ID structure might be different from the old feed.
                    # You might need to inspect the feedparser output if alerts aren't detected.
                    # For now, assuming alert.id is still a reliable unique identifier.
                    if alert.id not in seen_alert_ids:
                        new_alerts_found_this_cycle = True
                        logging.info(f"New Weather Alert: {alert.title}")
                        print(f"New Weather Alert: {alert.title}")
                        speak_weather_alert(tts_engine, alert.title, alert.summary, REPEATER_INFO)
                        seen_alert_ids.add(alert.id)

            if not new_alerts_found_this_cycle:
                logging.info(f"No new alerts in this cycle. Total unique alerts seen so far: {len(seen_alert_ids)}.")

            # Speak the repeater information at the end of every cycle, regardless of alerts
            if REPEATER_INFO:  # Ensure there's repeater info defined
                speak_message(tts_engine, REPEATER_INFO)

            logging.info(f"Waiting for {CHECK_INTERVAL} seconds before next check.")
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        logging.info("Weather alert monitoring stopped by user.")
    except Exception as e:
        logging.critical(f"An unexpected critical error occurred in the main loop: {e}", exc_info=True)
    finally:
        logging.info("Shutting down weather alert monitor.")
        if hasattr(tts_engine, 'stop'):
            tts_engine.stop()


if __name__ == "__main__":
    main()