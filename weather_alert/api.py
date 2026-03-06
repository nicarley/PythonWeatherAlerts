import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas
import pgeocode
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


NWS_STATION_API_URL_TEMPLATE = "https://api.weather.gov/stations/{station_id}"
NWS_POINTS_API_URL_TEMPLATE = "https://api.weather.gov/points/{latitude},{longitude}"
ALERTS_API_URL = "https://api.weather.gov/alerts/active"
ZONE_TYPES = ["forecast", "public", "marine", "coastal", "offshore", "fire", "weather"]


class ApiError(Exception):
    """Custom exception for API-related errors."""


class NwsApiClient:
    """Handles NWS API requests with retries and short-lived caches."""

    def __init__(self, user_agent: str, timeout: int = 10, forecast_ttl_s: int = 300, coords_ttl_s: int = 86400):
        self.user_agent = user_agent
        self.timeout = timeout
        self.forecast_ttl_s = forecast_ttl_s
        self.coords_ttl_s = coords_ttl_s
        self.headers = {"User-Agent": self.user_agent, "Accept": "application/geo+json"}
        self.pgeocode_client = pgeocode.Nominatim("us")

        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.7,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._coords_cache: Dict[str, Tuple[float, Tuple[float, float]]] = {}
        self._forecast_url_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}
        self._forecast_data_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def _get_json(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        use_headers = headers if headers else self.headers
        response = self.session.get(url, headers=use_headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _cache_get(cache: Dict[str, Tuple[float, Any]], key: str) -> Optional[Any]:
        cached = cache.get(key)
        if not cached:
            return None
        expires_at, value = cached
        if time.time() > expires_at:
            cache.pop(key, None)
            return None
        return value

    @staticmethod
    def _cache_set(cache: Dict[str, Tuple[float, Any]], key: str, value: Any, ttl_s: int) -> None:
        cache[key] = (time.time() + ttl_s, value)

    @staticmethod
    def _parse_lat_lon(location_id: str) -> Optional[Tuple[float, float]]:
        match = re.match(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$", location_id)
        if not match:
            return None
        lat = float(match.group(1))
        lon = float(match.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
        return None

    def _get_coordinates_for_zone(self, zone_id: str) -> Optional[Tuple[float, float]]:
        for zone_type in ZONE_TYPES:
            zone_url = f"https://api.weather.gov/zones/{zone_type}/{zone_id}"
            try:
                data = self._get_json(zone_url)
                coords = data.get("geometry", {}).get("coordinates")
                if not coords:
                    continue
                # Polygons are usually [[[lon,lat],...]]
                first = coords[0][0][0] if isinstance(coords[0][0], list) else coords[0][0]
                if isinstance(first, list) and len(first) >= 2:
                    return float(first[1]), float(first[0])
            except requests.RequestException:
                continue
            except (IndexError, TypeError, ValueError):
                continue
        return None

    def get_coordinates_for_location(self, location_id: str) -> Optional[Tuple[float, float]]:
        """Supports zip, airport/station IDs, lat/lon, county/zone IDs, and city,state."""
        if not location_id:
            return None

        processed_input = location_id.strip().upper()
        cached = self._cache_get(self._coords_cache, processed_input)
        if cached:
            return cached

        lat_lon = self._parse_lat_lon(processed_input)
        if lat_lon:
            self._cache_set(self._coords_cache, processed_input, lat_lon, self.coords_ttl_s)
            return lat_lon

        if processed_input.isdigit() and len(processed_input) == 5:
            location_info = self.pgeocode_client.query_postal_code(processed_input)
            if not location_info.empty and not pandas.isna(location_info.latitude):
                coords = (float(location_info.latitude), float(location_info.longitude))
                self._cache_set(self._coords_cache, processed_input, coords, self.coords_ttl_s)
                return coords

        zone_match = re.match(r"^[A-Z]{2}[A-Z]\d{3}$", processed_input)
        if zone_match:
            coords = self._get_coordinates_for_zone(processed_input)
            if coords:
                self._cache_set(self._coords_cache, processed_input, coords, self.coords_ttl_s)
                return coords

        if "," in processed_input:
            city_part, state_part = [p.strip() for p in processed_input.split(",", 1)]
            if city_part and len(state_part) == 2 and state_part.isalpha():
                city_df = self.pgeocode_client.query_location(city_part, state_code=state_part)
                if city_df is not None and not city_df.empty:
                    row = city_df.iloc[0]
                    if not pandas.isna(row.latitude) and not pandas.isna(row.longitude):
                        coords = (float(row.latitude), float(row.longitude))
                        self._cache_set(self._coords_cache, processed_input, coords, self.coords_ttl_s)
                        return coords

        nws_id_to_try = processed_input
        if len(processed_input) == 3 and processed_input.isalpha():
            nws_id_to_try = "K" + processed_input

        station_url = NWS_STATION_API_URL_TEMPLATE.format(station_id=nws_id_to_try)
        try:
            data = self._get_json(station_url)
            coords = data.get("geometry", {}).get("coordinates")
            if coords and len(coords) == 2:
                result = (float(coords[1]), float(coords[0]))
                self._cache_set(self._coords_cache, processed_input, result, self.coords_ttl_s)
                return result
        except requests.RequestException as e:
            logging.error("API error fetching station '%s': %s", nws_id_to_try, e)

        return None

    def validate_location(self, location_id: str) -> Tuple[bool, str]:
        coords = self.get_coordinates_for_location(location_id)
        if coords:
            return True, "Valid location input."
        return (
            False,
            "Could not resolve location. Try ZIP (62881), station (KSTL), lat/lon (38.63,-90.2), zone (ILC163), or city/state (St Louis,MO).",
        )

    def get_forecast_urls(self, lat: float, lon: float) -> Optional[Dict[str, str]]:
        cache_key = f"{lat:.4f},{lon:.4f}"
        cached = self._cache_get(self._forecast_url_cache, cache_key)
        if cached:
            return cached

        points_url = NWS_POINTS_API_URL_TEMPLATE.format(latitude=lat, longitude=lon)
        try:
            props = self._get_json(points_url).get("properties", {})
            data = {"hourly": props.get("forecastHourly"), "daily": props.get("forecast")}
            self._cache_set(self._forecast_url_cache, cache_key, data, self.forecast_ttl_s)
            return data
        except (requests.RequestException, ValueError) as e:
            logging.error("API error fetching gridpoint properties: %s", e)
            return None

    def get_forecast_data(self, url: str) -> Optional[Dict[str, Any]]:
        if not url:
            return None

        cached = self._cache_get(self._forecast_data_cache, url)
        if cached:
            return cached

        try:
            data = self._get_json(url)
            self._cache_set(self._forecast_data_cache, url, data, self.forecast_ttl_s)
            return data
        except (requests.RequestException, ValueError) as e:
            logging.error("API error fetching forecast data from %s: %s", url, e)
            return None

    @staticmethod
    def _normalize_alert(feature: Dict[str, Any]) -> Dict[str, Any]:
        props = feature.get("properties", {})
        event = props.get("event", "N/A")
        headline = props.get("headline") or event
        description = props.get("description") or "No summary available."
        title = f"{event}: {headline}" if headline and headline != event else event
        return {
            "id": props.get("id") or feature.get("id", "unknown-id"),
            "title": title,
            "summary": description,
            "link": props.get("@id") or props.get("uri") or "",
            "updated": props.get("updated"),
            "effective": props.get("effective"),
            "expires": props.get("expires"),
            "severity": (props.get("severity") or "").title(),
            "urgency": (props.get("urgency") or "").title(),
            "certainty": (props.get("certainty") or "").title(),
            "status": props.get("status", ""),
            "message_type": props.get("messageType", ""),
            "event": event,
            "area_desc": props.get("areaDesc", ""),
            "instruction": props.get("instruction", ""),
            "geometry": feature.get("geometry"),
        }

    def get_alerts(self, lat: float, lon: float) -> List[Dict[str, Any]]:
        params = (
            f"point={lat},{lon}"
            "&certainty=Possible,Likely,Observed"
            "&severity=Extreme,Severe,Moderate,Minor"
            "&urgency=Immediate,Future,Expected"
        )
        url = f"{ALERTS_API_URL}?{params}"
        try:
            data = self._get_json(url)
            features = data.get("features", [])
            return [self._normalize_alert(feature) for feature in features]
        except requests.RequestException as e:
            logging.error("Error fetching alerts from %s: %s", url, e)
            return []

    def build_alert_geojson(self, alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
        features: List[Dict[str, Any]] = []
        for alert in alerts:
            geometry = alert.get("geometry")
            if not geometry:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": alert.get("id", ""),
                        "title": alert.get("title", ""),
                        "severity": alert.get("severity", ""),
                        "event": alert.get("event", ""),
                    },
                    "geometry": geometry,
                }
            )
        return {"type": "FeatureCollection", "features": features}
