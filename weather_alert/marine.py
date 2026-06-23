import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests

from .security import first_payload_entry, safe_external_url


COOPS_DATA_API_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
COOPS_MAP_URL = "https://tidesandcurrents.noaa.gov/map/index.html"
COOPS_STATION_HOME_URL_TEMPLATE = "https://tidesandcurrents.noaa.gov/stationhome.html?id={station_id}"
COOPS_STATIONS_API_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"

MARINE_PRODUCTS = [
    {
        "key": "water_temp",
        "label": "Water Temp",
        "station_type": "watertemp",
        "product": "water_temperature",
        "detail": "Closest NOAA CO-OPS water-temperature station.",
    },
    {
        "key": "water_level",
        "label": "Water Level",
        "station_type": "waterlevels",
        "product": "water_level",
        "extra": {"datum": "MLLW"},
        "detail": "Closest NOAA CO-OPS water-level station.",
    },
    {
        "key": "tide",
        "label": "Next Tide",
        "station_type": "tidepredictions",
        "product": "predictions",
        "extra": {"date": "today", "datum": "MLLW", "interval": "hilo"},
        "detail": "Closest NOAA CO-OPS tide prediction station.",
    },
    {
        "key": "current",
        "label": "Current",
        "station_type": "currentpredictions",
        "product": "currents_predictions",
        "extra": {"date": "today", "interval": "max_slack"},
        "detail": "Closest NOAA CO-OPS current prediction station.",
    },
    {
        "key": "wind",
        "label": "Marine Wind",
        "station_type": "met",
        "product": "wind",
        "detail": "Closest NOAA CO-OPS meteorological station.",
    },
]


def moon_phase_info(now: Optional[datetime] = None) -> Dict[str, Any]:
    current = now or datetime.now()
    known_new_moon = datetime(2000, 1, 6, 18, 14)
    synodic_month = 29.530588853
    age = ((current - known_new_moon).total_seconds() / 86400.0) % synodic_month
    phase_breaks = [
        (1.84566, "New Moon"),
        (5.53699, "Waxing Crescent"),
        (9.22831, "First Quarter"),
        (12.91963, "Waxing Gibbous"),
        (16.61096, "Full Moon"),
        (20.30228, "Waning Gibbous"),
        (23.99361, "Last Quarter"),
        (27.68493, "Waning Crescent"),
        (synodic_month, "New Moon"),
    ]
    phase_name = next(name for limit, name in phase_breaks if age < limit)
    illumination = (1 - math.cos((2 * math.pi * age) / synodic_month)) / 2
    if phase_name in {"New Moon", "Full Moon"}:
        fishing_cue = "Stronger solunar pull; prioritize moving water around tide changes."
    elif "Quarter" in phase_name:
        fishing_cue = "Moderate solunar pull; wind, tide, and water clarity matter more."
    else:
        fishing_cue = "Subtle solunar pull; look for current edges, bait, and low-light windows."
    return {
        "phase": phase_name,
        "age": age,
        "illumination": illumination,
        "cue": fishing_cue,
    }


def max_optional(values: List[Optional[float]]) -> Optional[float]:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return max(numeric) if numeric else None


def distance_miles_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def coops_station_lat_lon(station: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    for lat_key, lon_key in [
        ("lat", "lng"),
        ("lat", "lon"),
        ("latitude", "longitude"),
    ]:
        try:
            lat = float(station.get(lat_key))
            lon = float(station.get(lon_key))
            return lat, lon
        except (TypeError, ValueError):
            continue
    return None


def coops_station_url(station_id: str) -> str:
    if not station_id:
        return COOPS_MAP_URL
    return COOPS_STATION_HOME_URL_TEMPLATE.format(station_id=station_id)


def marine_card_detail(data: Any, fallback: str) -> str:
    if not isinstance(data, dict) or not data:
        return fallback
    station = str(data.get("station") or "Unknown station")
    distance = data.get("distance_miles")
    distance_text = f"{float(distance):.1f} mi away" if isinstance(distance, (int, float)) else "distance unavailable"
    observed = str(data.get("detail") or "").strip()
    observed_text = f" \N{MIDDLE DOT} {observed}" if observed and observed.lower() != "latest" else ""
    return f"{station} \N{MIDDLE DOT} {distance_text}{observed_text}"


def fishing_resource_links(
    current_coords: Optional[Tuple[float, float]],
    marine_data: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str, str]]:
    coords_text = ""
    marine_url = "https://marine.weather.gov/"
    if current_coords:
        lat, lon = current_coords
        coords_text = f" near {lat:.3f}, {lon:.3f}"
        marine_url = f"https://marine.weather.gov/MapClick.php?lat={lat}&lon={lon}"

    links: List[Tuple[str, str, str]] = []
    for data in (marine_data or {}).values():
        if not isinstance(data, dict):
            continue
        title = str(data.get("label") or "NOAA station")
        station = str(data.get("station") or "")
        distance = data.get("distance_miles")
        distance_text = f" \N{MIDDLE DOT} {float(distance):.1f} mi away" if isinstance(distance, (int, float)) else ""
        links.append(
            (
                title,
                safe_external_url(data.get("station_url") or data.get("url") or COOPS_MAP_URL, COOPS_MAP_URL),
                f"{station}{distance_text}. {data.get('description', '')}",
            )
        )

    links.extend([
        (
            "NOAA Tides & Currents",
            COOPS_MAP_URL,
            f"Tides, currents, water levels, water temperature, winds, pressure, and visibility{coords_text}.",
        ),
        (
            "NDBC Buoy Map",
            "https://www.ndbc.noaa.gov/obs.shtml",
            "Buoys and coastal stations for sea-surface temperature, wave height/period, wind, and pressure.",
        ),
        (
            "NWS Marine Forecast",
            marine_url,
            "Official marine forecast around the selected point, useful for seas, wind, storms, and advisories.",
        ),
    ])
    return links


class MarineDataService:
    """Fetches and summarizes nearest NOAA CO-OPS marine data for a selected point."""

    def __init__(self, session: requests.Session, timeout: int = 8):
        self.session = session
        self.timeout = timeout
        self.station_cache: Dict[str, List[Dict[str, Any]]] = {}

    def fetch_stations(self, station_type: str) -> List[Dict[str, Any]]:
        if station_type in self.station_cache:
            return self.station_cache[station_type]

        url = f"{COOPS_STATIONS_API_URL}?{urlencode({'type': station_type})}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            stations = payload.get("stations", [])
            if isinstance(stations, list):
                self.station_cache[station_type] = stations
                return stations
        except (requests.RequestException, ValueError) as exc:
            logging.debug("CO-OPS station lookup failed for %s: %s", station_type, exc)

        self.station_cache[station_type] = []
        return []

    def nearest_station(self, lat: float, lon: float, station_type: str) -> Optional[Dict[str, Any]]:
        nearest = None
        nearest_distance = None
        for station in self.fetch_stations(station_type):
            station_coords = coops_station_lat_lon(station)
            if not station_coords:
                continue
            distance = distance_miles_between(lat, lon, station_coords[0], station_coords[1])
            if nearest_distance is None or distance < nearest_distance:
                nearest = dict(station)
                nearest_distance = distance
        if nearest is not None and nearest_distance is not None:
            nearest["distance_miles"] = nearest_distance
        return nearest

    @staticmethod
    def data_url(station_id: str, product: str, extra: Optional[Dict[str, str]] = None) -> str:
        params = {
            "date": "latest",
            "station": station_id,
            "product": product,
            "time_zone": "lst_ldt",
            "units": "english",
            "format": "json",
        }
        if extra:
            params.update(extra)
        return f"{COOPS_DATA_API_URL}?{urlencode(params)}"

    def fetch_product_summary(
        self,
        station_id: str,
        product: str,
        extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        data_url = self.data_url(station_id, product, extra)
        try:
            response = self.session.get(data_url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            return {"value": "Unavailable", "detail": str(exc), "url": data_url}

        if payload.get("error"):
            return {
                "value": "Unavailable",
                "detail": str(payload.get("error", {}).get("message", "No data")),
                "url": data_url,
            }

        if product == "wind":
            latest = first_payload_entry(payload.get("data", []))
            speed = latest.get("s")
            gust = latest.get("g")
            direction = latest.get("dr") or latest.get("d")
            value = f"{speed} kt" if speed not in {None, ""} else "Unavailable"
            if gust not in {None, ""}:
                value += f" gust {gust} kt"
            if direction not in {None, ""}:
                value += f" {direction}"
            return {"value": value, "detail": latest.get("t", "latest"), "url": data_url}

        if product in {"water_temperature", "water_level"}:
            latest = first_payload_entry(payload.get("data", []))
            raw_value = latest.get("v")
            unit = "\N{DEGREE SIGN}F" if product == "water_temperature" else "ft"
            value = f"{raw_value}{unit}" if raw_value not in {None, ""} else "Unavailable"
            return {"value": value, "detail": latest.get("t", "latest"), "url": data_url}

        first_prediction = first_payload_entry(payload.get("predictions", []))
        if first_prediction:
            tide_type = first_prediction.get("type", "")
            raw_value = first_prediction.get("v")
            value = f"{tide_type} {raw_value} ft".strip()
            return {"value": value, "detail": first_prediction.get("t", "today"), "url": data_url}

        first_current = first_payload_entry(payload.get("current_predictions", []))
        if first_current:
            speed = first_current.get("Velocity_Major") or first_current.get("velocity") or first_current.get("v")
            direction = first_current.get("meanFloodDir") or first_current.get("Direction") or first_current.get("d")
            value = f"{speed} kt" if speed not in {None, ""} else "Available"
            if direction not in {None, ""}:
                value += f" {direction}"
            return {
                "value": value,
                "detail": first_current.get("Time") or first_current.get("t") or "today",
                "url": data_url,
            }

        return {"value": "Unavailable", "detail": "No recent product values returned.", "url": data_url}

    def fetch_nearest_marine_data(self, lat: float, lon: float) -> Dict[str, Any]:
        nearest: Dict[str, Any] = {}
        for config in MARINE_PRODUCTS:
            try:
                station = self.nearest_station(lat, lon, str(config["station_type"]))
                if not station:
                    nearest[str(config["key"])] = {
                        "label": config["label"],
                        "value": "Unavailable",
                        "detail": "No nearby NOAA CO-OPS station list was returned.",
                        "station": "",
                        "distance_miles": None,
                        "url": COOPS_MAP_URL,
                    }
                    continue

                station_id = str(station.get("id") or station.get("station_id") or "")
                summary = self.fetch_product_summary(
                    station_id,
                    str(config["product"]),
                    config.get("extra"),
                )
                nearest[str(config["key"])] = {
                    "label": config["label"],
                    "value": summary.get("value", "Unavailable"),
                    "detail": summary.get("detail") or config.get("detail", ""),
                    "station": station.get("name") or station_id,
                    "station_id": station_id,
                    "distance_miles": station.get("distance_miles"),
                    "url": summary.get("url") or coops_station_url(station_id),
                    "station_url": coops_station_url(station_id),
                    "description": config.get("detail", ""),
                }
            except Exception as exc:
                logging.debug("Marine product lookup failed for %s: %s", config.get("key"), exc)
                nearest[str(config["key"])] = {
                    "label": config["label"],
                    "value": "Unavailable",
                    "detail": str(exc),
                    "station": "",
                    "distance_miles": None,
                    "url": COOPS_MAP_URL,
                }
        return nearest
