import requests
import feedparser
import pyttsx3
import time
import logging

# --- Configuration ---
NWS_STATION_ID = "KSLO"  # Target NWS Station ID
CHECK_INTERVAL = 900  # Check every 15 minutes (in seconds)

# URL format for fetching alerts for a specific point (latitude, longitude)
# The {lat} and {lon} placeholders will be filled dynamically
ALERTS_URL_POINT_FORMAT = "https://api.weather.gov/alerts/active.atom?point={lat}%2C{lon}&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Future%2CExpected"

# NWS API endpoint for station details (to get coordinates)
NWS_STATION_API_URL_FORMAT = "https://api.weather.gov/stations/{station_id}"

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

def fetch_station_coordinates(station_id):
    """
    Fetches the latitude and longitude for a given NWS station ID.
    Returns a tuple (latitude, longitude) or None if an error occurs.
    """
    if not station_id:
        logging.error("Station ID is empty. Cannot fetch coordinates.")
        return None

    station_api_url = NWS_STATION_API_URL_FORMAT.format(station_id=station_id.upper())
    # It's good practice to include a User-Agent header for API requests
    headers = {
        'User-Agent': 'PythonWeatherAlertScript/1.0 (contact@example.com)', # Customize this
        'Accept': 'application/geo+json' # NWS API prefers this for geo data
    }
    logging.info(f"Fetching coordinates for station ID: {station_id} from {station_api_url}")

    try:
        response = requests.get(station_api_url, headers=headers, timeout=10)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        data = response.json()

        geometry = data.get('geometry')
        if geometry and geometry.get('type') == 'Point':
            coordinates = geometry.get('coordinates')
            # NWS API returns [longitude, latitude]
            if coordinates and len(coordinates) == 2:
                longitude, latitude = coordinates[0], coordinates[1]
                logging.info(f"Successfully fetched coordinates for {station_id}: Lat={latitude}, Lon={longitude}")
                return latitude, longitude
            else:
                logging.error(f"Could not parse coordinates from station data for {station_id}. Coordinates: {coordinates}")
        else:
            logging.error(f"Geometry data not found or not a Point for station {station_id}. Geometry: {geometry}")
        return None
    except requests.exceptions.HTTPError as http_err:
        if http_err.response.status_code == 404:
            logging.error(f"NWS Station ID '{station_id}' not found (404 error) at {station_api_url}.")
        else:
            logging.error(f"HTTP error fetching station data for {station_id}: {http_err} from {station_api_url}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error fetching station data for {station_id}: {e} from {station_api_url}")
    except ValueError: # Includes JSONDecodeError
        logging.error(f"Failed to decode JSON response for station {station_id} from {station_api_url}")
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching coordinates for {station_id}: {e}")
    return None


def get_alerts(alerts_url_for_point):
    """Fetches weather alerts from the provided URL for a specific point."""
    if not alerts_url_for_point:
        logging.warning("Alerts URL is not provided. Skipping alert fetch.")
        return []
    try:
        # NWS API for alerts also benefits from a User-Agent
        headers = {'User-Agent': 'PythonWeatherAlertScript/1.0 (contact@example.com)'} # Customize
        response = requests.get(alerts_url_for_point, headers=headers, timeout=10)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        return feed.entries
    except requests.exceptions.Timeout:
        logging.error(f"Timeout while trying to fetch alerts from {alerts_url_for_point}")
    except requests.exceptions.HTTPError as http_err:
        logging.error(
            f"HTTP error occurred fetching alerts: {http_err} from {alerts_url_for_point} - Status code: {http_err.response.status_code if http_err.response else 'N/A'}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching alerts from {alerts_url_for_point}: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred in get_alerts ({alerts_url_for_point}): {e}")
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


def speak_message(engine, message_text):
    """Speaks a given message using the TTS engine."""
    if not message_text:
        logging.debug("speak_message called with empty text, skipping.")
        return
    try:
        engine.say(message_text)
        engine.runAndWait()
        logging.info(f"Spoken: {message_text}")
    except Exception as e:
        logging.error(f"Error during text-to-speech for message '{message_text}': {e}")


def main():
    seen_alert_ids = set()
    tts_engine = initialize_tts_engine()

    logging.info(f"Monitoring weather alerts for NWS Station ID: {NWS_STATION_ID} every {CHECK_INTERVAL} seconds.")
    if REPEATER_INFO:
        logging.info(f"Repeater line to be spoken each cycle: '{REPEATER_INFO}'")

    # Fetch initial coordinates for the station.
    # In a long-running script, you might want to refresh this periodically
    # or handle cases where the station data might change, though it's rare.
    current_coordinates = fetch_station_coordinates(NWS_STATION_ID)
    if not current_coordinates:
        logging.critical(f"Could not fetch initial coordinates for station {NWS_STATION_ID}. Alerts cannot be monitored. Exiting.")
        return # Or handle this more gracefully, e.g., retry after some time

    latitude, longitude = current_coordinates
    alerts_url = ALERTS_URL_POINT_FORMAT.format(lat=latitude, lon=longitude)
    logging.info(f"Alerts will be fetched from: {alerts_url}")

    try:
        while True:
            # In a more robust setup, you might re-fetch coordinates if alerts_url becomes invalid
            # or if there's a way to detect station data changes. For now, we use the initial one.

            alerts = get_alerts(alerts_url)
            new_alerts_found_this_cycle = False

            if alerts:
                for alert in alerts:
                    if not hasattr(alert, 'id') or not hasattr(alert, 'title'):
                        logging.warning(f"Skipping alert with missing 'id' or 'title': {alert}")
                        continue
                    if alert.id not in seen_alert_ids:
                        new_alerts_found_this_cycle = True
                        logging.info(f"New Weather Alert: {alert.title}")
                        print(f"New Weather Alert: {alert.title}") # For immediate console visibility
                        summary = getattr(alert, 'summary', "No summary available.")
                        speak_weather_alert(tts_engine, alert.title, summary, REPEATER_INFO)
                        seen_alert_ids.add(alert.id)

            if not new_alerts_found_this_cycle:
                logging.info(f"No new alerts in this cycle. Total unique alerts seen so far: {len(seen_alert_ids)}.")

            if REPEATER_INFO:
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
            # Ensure the engine is not busy before trying to stop, though runAndWait should handle this.
            if tts_engine.isBusy():
                try:
                    tts_engine.stop()
                except Exception as e_stop:
                    logging.error(f"Error trying to stop TTS engine: {e_stop}")


if __name__ == "__main__":
    main()