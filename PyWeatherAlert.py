import requests  # Used for making HTTP requests to fetch data from web APIs.
import feedparser  # Used for parsing ATOM and RSS feeds, specifically for NWS alerts.
import pyttsx3  # Used for text-to-speech (TTS) functionality.
import time  # Used for adding delays (e.g., between checks) and for timestamping logs.
import logging  # Used for logging application events, errors, and information.

# --- Configuration ---
NWS_STATION_ID = "KSLO"  # Target NWS/AIRPORT Station ID for which to fetch weather alerts.
CHECK_INTERVAL = 900  # Time in seconds between checks for new weather alerts (e.g., 900 seconds = 15 minutes).
# Define the repeater information as a constant. This text will be spoken after alerts or periodically.
REPEATER_INFO = "Repeater, GMRSCALLSIGN, Frequencies (Change text in quotes)"


# URL format for fetching active alerts for a specific geographic point (latitude, longitude).
# The {lat} and {lon} placeholders will be replaced with actual coordinates.
# Filters are applied for certainty, severity, and urgency of alerts.
ALERTS_URL_POINT_FORMAT = "https://api.weather.gov/alerts/active.atom?point={lat}%2C{lon}&certainty=Possible%2CLikely%2CObserved&severity=Extreme%2CSevere%2CModerate%2CMinor&urgency=Future%2CExpected"

# NWS API endpoint format for fetching details about a specific weather station,
# which includes its geographic coordinates. The {station_id} will be replaced.
NWS_STATION_API_URL_FORMAT = "https://api.weather.gov/stations/{station_id}"


# --- Logging Setup ---
# Configures basic logging:
# - Level: INFO (logs INFO, WARNING, ERROR, CRITICAL messages)
# - Format: Includes timestamp, log level, and the message.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Functions ---
def initialize_tts_engine():
    """
    Initializes and returns the text-to-speech (TTS) engine.
    If initialization fails, it returns a dummy engine that logs messages
    instead of speaking them, allowing the script to continue running.
    """
    try:
        engine = pyttsx3.init()  # Attempt to initialize the TTS engine.
        if engine is None:  # Some pyttsx3 implementations might return None on failure.
            raise RuntimeError("pyttsx3.init() returned None")
        logging.info("TTS engine initialized successfully.")
        return engine  # Return the initialized engine.
    except Exception as e:
        # Log the error if TTS initialization fails.
        logging.error(f"Failed to initialize TTS engine: {e}. Text-to-speech will use a fallback.")

        # Define a dummy TTS engine class to be used as a fallback.
        class DummyEngine:
            def say(self, text, name=None): # `name` arg for potential future pyttsx3 compatibility
                """Logs the text instead of speaking it."""
                logging.info(f"TTS (Fallback): {text}")

            def runAndWait(self):
                """Does nothing, as there's no speech to wait for."""
                pass

            def stop(self):
                """Does nothing."""
                pass

            def isBusy(self):
                """Always returns False, as it's never 'speaking'."""
                return False

            def getProperty(self, name):
                """Returns None for any requested property."""
                return None

            def setProperty(self, name, value):
                """Does nothing when trying to set a property."""
                pass

        return DummyEngine() # Return an instance of the dummy engine.

def fetch_station_coordinates(station_id):
    """
    Fetches the latitude and longitude for a given NWS station ID.

    Args:
        station_id (str): The NWS station identifier (e.g., "KSLO").

    Returns:
        tuple: A tuple containing (latitude, longitude) if successful,
               otherwise None.
    """
    if not station_id:
        logging.error("Station ID is empty. Cannot fetch coordinates.")
        return None

    # Format the API URL with the provided station ID (converted to uppercase).
    station_api_url = NWS_STATION_API_URL_FORMAT.format(station_id=station_id.upper())
    # It's good practice to include a User-Agent header for API requests.
    # Customize 'YourAppName/Version (yourcontact@example.com)' as appropriate.
    headers = {
        'User-Agent': 'PythonWeatherAlertScript/1.0 (contact@example.com)', # Customize this
        'Accept': 'application/geo+json' # NWS API prefers this format for geographic data.
    }
    logging.info(f"Fetching coordinates for station ID: {station_id} from {station_api_url}")

    try:
        # Make the GET request to the NWS API.
        response = requests.get(station_api_url, headers=headers, timeout=10) # 10-second timeout.
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx status codes).
        data = response.json()  # Parse the JSON response.

        # Extract geometry data.
        geometry = data.get('geometry')
        if geometry and geometry.get('type') == 'Point':
            coordinates = geometry.get('coordinates')
            # NWS API returns coordinates in [longitude, latitude] order.
            if coordinates and len(coordinates) == 2:
                longitude, latitude = coordinates[0], coordinates[1]
                logging.info(f"Successfully fetched coordinates for {station_id}: Lat={latitude}, Lon={longitude}")
                return latitude, longitude # Return the extracted latitude and longitude.
            else:
                logging.error(f"Could not parse coordinates from station data for {station_id}. Coordinates: {coordinates}")
        else:
            logging.error(f"Geometry data not found or not a Point for station {station_id}. Geometry: {geometry}")
        return None # Return None if coordinates couldn't be parsed.
    except requests.exceptions.HTTPError as http_err:
        # Handle HTTP errors specifically.
        if http_err.response.status_code == 404:
            logging.error(f"NWS Station ID '{station_id}' not found (404 error) at {station_api_url}.")
        else:
            logging.error(f"HTTP error fetching station data for {station_id}: {http_err} from {station_api_url}")
    except requests.exceptions.RequestException as e:
        # Handle other network-related errors (e.g., DNS failure, connection refused).
        logging.error(f"Network error fetching station data for {station_id}: {e} from {station_api_url}")
    except ValueError: # Includes JSONDecodeError if response is not valid JSON.
        logging.error(f"Failed to decode JSON response for station {station_id} from {station_api_url}")
    except Exception as e:
        # Catch any other unexpected errors.
        logging.error(f"An unexpected error occurred while fetching coordinates for {station_id}: {e}")
    return None # Return None in case of any error.


def get_alerts(alerts_url_for_point):
    """
    Fetches weather alerts from the provided NWS ATOM feed URL for a specific point.

    Args:
        alerts_url_for_point (str): The fully formatted URL to fetch alerts from.

    Returns:
        list: A list of alert entries (parsed by feedparser). Returns an empty
              list if an error occurs or no alerts are found.
    """
    if not alerts_url_for_point:
        logging.warning("Alerts URL is not provided. Skipping alert fetch.")
        return [] # Return an empty list if no URL is given.
    try:
        # NWS API for alerts also benefits from a User-Agent.
        headers = {'User-Agent': 'PythonWeatherAlertScript/1.0 (contact@example.com)'} # Customize
        # Make the GET request to the alerts API.
        response = requests.get(alerts_url_for_point, headers=headers, timeout=10) # 10-second timeout.
        response.raise_for_status() # Check for HTTP errors.
        feed = feedparser.parse(response.content) # Parse the ATOM feed content.
        return feed.entries # Return the list of alert entries.
    except requests.exceptions.Timeout:
        logging.error(f"Timeout while trying to fetch alerts from {alerts_url_for_point}")
    except requests.exceptions.HTTPError as http_err:
        # Log HTTP errors, including status code if available.
        logging.error(
            f"HTTP error occurred fetching alerts: {http_err} from {alerts_url_for_point} - Status code: {http_err.response.status_code if http_err.response else 'N/A'}")
    except requests.exceptions.RequestException as e:
        # Log other network-related errors.
        logging.error(f"Error fetching alerts from {alerts_url_for_point}: {e}")
    except Exception as e:
        # Log any other unexpected errors during alert fetching or parsing.
        logging.error(f"An unexpected error occurred in get_alerts ({alerts_url_for_point}): {e}")
    return [] # Return an empty list in case of any error.


def speak_weather_alert(engine, alert_title, alert_summary, additional_info=""):
    """
    Constructs a message from alert details and speaks it using the TTS engine.

    Args:
        engine: The initialized TTS engine instance.
        alert_title (str): The title of the weather alert.
        alert_summary (str): The summary or details of the alert.
        additional_info (str, optional): Extra information to append to the message (e.g., repeater info).
    """
    # Construct the core alert message.
    message = f"Weather Alert: {alert_title}. Details: {alert_summary}"
    if additional_info:
        # Append additional info, ensuring proper punctuation if needed.
        if message and not message.endswith(('.', '!', '?')):
            message += "."
        message += f" {additional_info}"
    try:
        engine.say(message) # Queue the message for speaking.
        engine.runAndWait() # Block until speaking is complete.
    except Exception as e:
        logging.error(f"Error during text-to-speech: {e}")


def speak_message(engine, message_text):
    """
    Speaks a given message string using the TTS engine.

    Args:
        engine: The initialized TTS engine instance.
        message_text (str): The text to be spoken.
    """
    if not message_text: # Avoid trying to speak empty messages.
        logging.debug("speak_message called with empty text, skipping.")
        return
    try:
        engine.say(message_text) # Queue the message.
        engine.runAndWait() # Block until speaking is complete.
        logging.info(f"Spoken: {message_text}")
    except Exception as e:
        logging.error(f"Error during text-to-speech for message '{message_text}': {e}")


def main():
    """
    Main function to run the weather alert monitoring script.
    It periodically checks for new alerts and announces them.
    """
    seen_alert_ids = set() # A set to store IDs of alerts already announced, to avoid repetition.
    tts_engine = initialize_tts_engine() # Initialize the TTS engine.

    logging.info(f"Monitoring weather alerts for NWS Station ID: {NWS_STATION_ID} every {CHECK_INTERVAL} seconds.")
    if REPEATER_INFO:
        logging.info(f"Repeater line to be spoken each cycle: '{REPEATER_INFO}'")

    # Fetch initial coordinates for the configured NWS station.
    # In a long-running script, you might want to refresh this periodically
    # or handle cases where the station data might change, though it's rare.
    current_coordinates = fetch_station_coordinates(NWS_STATION_ID)
    if not current_coordinates:
        # If coordinates can't be fetched, alerts cannot be monitored for a point.
        logging.critical(f"Could not fetch initial coordinates for station {NWS_STATION_ID}. Alerts cannot be monitored. Exiting.")
        return # Exit the script if initial setup fails.

    latitude, longitude = current_coordinates # Unpack the coordinates.
    # Format the alerts URL with the fetched latitude and longitude.
    alerts_url = ALERTS_URL_POINT_FORMAT.format(lat=latitude, lon=longitude)
    logging.info(f"Alerts will be fetched from: {alerts_url}")

    try:
        # Main loop for continuously checking alerts.
        while True:
            # In a more robust setup, you might re-fetch coordinates if alerts_url becomes invalid
            # or if there's a way to detect station data changes. For now, we use the initial one.

            alerts = get_alerts(alerts_url) # Fetch current active alerts.
            new_alerts_found_this_cycle = False # Flag to track if new alerts are found in this iteration.

            if alerts:
                for alert in alerts:
                    # Ensure the alert has an 'id' and 'title' attribute before processing.
                    if not hasattr(alert, 'id') or not hasattr(alert, 'title'):
                        logging.warning(f"Skipping alert with missing 'id' or 'title': {alert}")
                        continue
                    # Check if this alert has been seen before.
                    if alert.id not in seen_alert_ids:
                        new_alerts_found_this_cycle = True
                        logging.info(f"New Weather Alert: {alert.title}")
                        print(f"New Weather Alert: {alert.title}") # For immediate console visibility.
                        # Get alert summary, defaulting if not present.
                        summary = getattr(alert, 'summary', "No summary available.")
                        # Speak the new alert along with repeater information.
                        speak_weather_alert(tts_engine, alert.title, summary, REPEATER_INFO)
                        seen_alert_ids.add(alert.id) # Add the alert ID to the set of seen alerts.

            if not new_alerts_found_this_cycle:
                # Log if no new alerts were found in this cycle.
                logging.info(f"No new alerts in this cycle. Total unique alerts seen so far: {len(seen_alert_ids)}.")

            # If REPEATER_INFO is configured, speak it at the end of each cycle.
            if REPEATER_INFO:
                speak_message(tts_engine, REPEATER_INFO)

            # Wait for the defined interval before the next check.
            logging.info(f"Waiting for {CHECK_INTERVAL} seconds before next check.")
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        # Handle graceful shutdown if the user presses Ctrl+C.
        logging.info("Weather alert monitoring stopped by user.")
    except Exception as e:
        # Log any other unexpected critical errors that occur in the main loop.
        logging.critical(f"An unexpected critical error occurred in the main loop: {e}", exc_info=True) # exc_info=True logs traceback.
    finally:
        # This block executes whether the loop exits normally or due to an exception.
        logging.info("Shutting down weather alert monitor.")
        if hasattr(tts_engine, 'stop'): # Check if the engine has a 'stop' method.
            # Ensure the engine is not busy before trying to stop, though runAndWait should handle this.
            if tts_engine.isBusy():
                try:
                    tts_engine.stop() # Attempt to stop any ongoing speech.
                except Exception as e_stop:
                    logging.error(f"Error trying to stop TTS engine: {e_stop}")


# Standard Python idiom: ensure the main() function is called only when the script is executed directly.
if __name__ == "__main__":
    main()