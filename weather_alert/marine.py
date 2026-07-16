import logging
import math
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests

from .security import first_payload_entry, safe_external_url


COOPS_DATA_API_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
COOPS_MAP_URL = "https://tidesandcurrents.noaa.gov/map/index.html"
COOPS_STATION_HOME_URL_TEMPLATE = "https://tidesandcurrents.noaa.gov/stationhome.html?id={station_id}"
COOPS_STATIONS_API_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
NDBC_ACTIVE_STATIONS_URL = "https://www.ndbc.noaa.gov/activestations.xml"
NDBC_REALTIME_URL_TEMPLATE = "https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
NDBC_STATION_URL_TEMPLATE = "https://www.ndbc.noaa.gov/station_page.php?station={station_id}"

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
    {
        "key": "salinity",
        "label": "Salinity",
        "station_type": "cond",
        "product": "salinity",
        "detail": "Closest NOAA CO-OPS salinity station.",
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


def fishing_condition_outlook(metrics: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """Return a transparent trip-conditions heuristic, not a catch forecast."""
    if not any(isinstance(value, (int, float)) for value in metrics.values()):
        return {
            "score": 50,
            "label": "Data limited",
            "positives": [],
            "cautions": ["Not enough current weather or marine data is available for an outlook."],
            "disclaimer": "Weather and access heuristic only; it does not predict fish activity or catch rate.",
        }

    score = 82
    positives: List[str] = []
    cautions: List[str] = []

    peak_wind = metrics.get("peak_wind_mph")
    peak_gust = metrics.get("peak_gust_mph")
    thunder = metrics.get("thunder_pct")
    precip = metrics.get("precip_pct")
    visibility = metrics.get("visibility_miles")
    wave_height = metrics.get("wave_height_ft")
    wave_period = metrics.get("wave_period_s")
    pressure_tendency = metrics.get("pressure_tendency_hpa")

    if isinstance(peak_gust, (int, float)) and peak_gust >= 30:
        score -= 32
        cautions.append("Strong gusts can make exposed water hazardous.")
    elif isinstance(peak_gust, (int, float)) and peak_gust >= 20:
        score -= 16
        cautions.append("Gusts favor protected banks, coves, and shorter runs.")
    elif isinstance(peak_wind, (int, float)) and peak_wind <= 10:
        score += 6
        positives.append("Light wind should improve boat control and presentation.")

    if isinstance(thunder, (int, float)) and thunder >= 30:
        score -= 38
        cautions.append("Thunder risk is the dominant safety constraint.")
    elif isinstance(thunder, (int, float)) and thunder >= 15:
        score -= 18
        cautions.append("Monitor radar and keep a fast route off the water.")
    elif isinstance(thunder, (int, float)) and thunder < 10:
        positives.append("Low modeled thunder probability.")

    if isinstance(precip, (int, float)) and precip >= 70:
        score -= 12
        cautions.append("High rain chances may change runoff, clarity, and access.")
    elif isinstance(precip, (int, float)) and precip >= 40:
        score -= 6
        cautions.append("Rain may create short feeding windows but reduce comfort.")

    if isinstance(visibility, (int, float)) and visibility < 2:
        score -= 20
        cautions.append("Very low visibility increases navigation risk.")
    elif isinstance(visibility, (int, float)) and visibility < 5:
        score -= 8
        cautions.append("Reduced visibility may affect safe running.")
    elif isinstance(visibility, (int, float)) and visibility >= 8:
        positives.append("Good observed visibility.")

    if isinstance(wave_height, (int, float)) and wave_height >= 6:
        score -= 28
        cautions.append("Large significant waves are unsuitable for many small craft.")
    elif isinstance(wave_height, (int, float)) and wave_height >= 4:
        score -= 15
        cautions.append("Elevated waves may limit exposed-water options.")
    elif isinstance(wave_height, (int, float)) and wave_height <= 2:
        positives.append("Nearby buoy reports relatively low waves.")

    if (
        isinstance(wave_height, (int, float))
        and wave_height >= 3
        and isinstance(wave_period, (int, float))
        and wave_period <= 5
    ):
        score -= 8
        cautions.append("Short-period waves indicate a steeper, choppier sea state.")

    if isinstance(pressure_tendency, (int, float)):
        if pressure_tendency <= -2:
            cautions.append("Pressure is falling quickly; conditions may be changing.")
        elif abs(pressure_tendency) < 1:
            positives.append("Pressure has been comparatively steady.")

    score = max(0, min(100, score))
    if score >= 82:
        label = "Favorable"
    elif score >= 62:
        label = "Mixed"
    elif score >= 42:
        label = "Challenging"
    else:
        label = "Poor / safety limited"

    return {
        "score": score,
        "label": label,
        "positives": positives,
        "cautions": cautions,
        "disclaimer": "Weather and access heuristic only; it does not predict fish activity or catch rate.",
    }


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
        self.ndbc_station_cache: Optional[List[Dict[str, Any]]] = None

    def fetch_stations(self, station_type: str) -> List[Dict[str, Any]]:
        if station_type in self.station_cache:
            return self.station_cache[station_type]

        url = f"{COOPS_STATIONS_API_URL}?{urlencode({'type': station_type})}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            stations = payload.get("stations") or payload.get("stationList") or []
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

        if product in {"water_temperature", "water_level", "salinity"}:
            latest = first_payload_entry(payload.get("data", []))
            raw_value = latest.get("v")
            unit = {
                "water_temperature": "\N{DEGREE SIGN}F",
                "water_level": " ft",
                "salinity": " ppt",
            }[product]
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

    def fetch_ndbc_stations(self) -> List[Dict[str, Any]]:
        if self.ndbc_station_cache is not None:
            return self.ndbc_station_cache
        try:
            response = self.session.get(NDBC_ACTIVE_STATIONS_URL, timeout=self.timeout)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            stations = []
            for element in root.findall(".//station"):
                try:
                    stations.append(
                        {
                            "id": str(element.attrib.get("id") or ""),
                            "name": str(element.attrib.get("name") or element.attrib.get("id") or "NDBC station"),
                            "lat": float(element.attrib["lat"]),
                            "lon": float(element.attrib["lon"]),
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            self.ndbc_station_cache = stations
        except Exception as exc:
            logging.debug("NDBC active-station lookup failed: %s", exc)
            self.ndbc_station_cache = []
        return self.ndbc_station_cache

    @staticmethod
    def _ndbc_number(value: Any) -> Optional[float]:
        text = str(value or "").strip()
        if not text or text.upper() in {"MM", "N/A"}:
            return None
        try:
            numeric = float(text)
        except (TypeError, ValueError):
            return None
        return numeric

    def fetch_ndbc_observation(self, station_id: str) -> Dict[str, Any]:
        url = NDBC_REALTIME_URL_TEMPLATE.format(station_id=station_id)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        lines = [line.strip() for line in response.text.splitlines() if line.strip()]
        header = next((line.lstrip("#").split() for line in lines if line.startswith("#YY")), [])
        data_line = next((line.split() for line in lines if not line.startswith("#")), [])
        if not header or not data_line:
            return {}
        row = dict(zip(header, data_line))

        def number(field: str) -> Optional[float]:
            return self._ndbc_number(row.get(field))

        year = int(number("YY") or 0)
        if year and year < 100:
            year += 2000
        observed_at = ""
        try:
            observed_at = datetime(
                year,
                int(number("MM") or 1),
                int(number("DD") or 1),
                int(number("hh") or 0),
                int(number("mm") or 0),
            ).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            observed_at = "Latest NDBC observation"

        def c_to_f(value: Optional[float]) -> Optional[float]:
            return value * 9 / 5 + 32 if value is not None else None

        def mps_to_knots(value: Optional[float]) -> Optional[float]:
            return value * 1.94384 if value is not None else None

        return {
            "observed_at": observed_at,
            "wind_direction_deg": number("WDIR"),
            "wind_speed_kt": mps_to_knots(number("WSPD")),
            "gust_kt": mps_to_knots(number("GST")),
            "wave_height_ft": number("WVHT") * 3.28084 if number("WVHT") is not None else None,
            "dominant_period_s": number("DPD"),
            "average_period_s": number("APD"),
            "wave_direction_deg": number("MWD"),
            "pressure_inhg": number("PRES") * 0.029529983 if number("PRES") is not None else None,
            "pressure_tendency_hpa": number("PTDY"),
            "air_temp_f": c_to_f(number("ATMP")),
            "water_temp_f": c_to_f(number("WTMP")),
            "dewpoint_f": c_to_f(number("DEWP")),
            "visibility_nm": number("VIS"),
            "tide_ft": number("TIDE"),
            "url": url,
        }

    def fetch_nearest_ndbc_data(self, lat: float, lon: float) -> Dict[str, Any]:
        candidates = []
        for station in self.fetch_ndbc_stations():
            distance = distance_miles_between(lat, lon, float(station["lat"]), float(station["lon"]))
            candidates.append((distance, station))
        candidates.sort(key=lambda item: item[0])

        for distance, station in candidates[:3]:
            station_id = str(station.get("id") or "")
            try:
                observation = self.fetch_ndbc_observation(station_id)
            except Exception as exc:
                logging.debug("NDBC observation lookup failed for %s: %s", station_id, exc)
                continue
            useful_fields = [
                "wave_height_ft", "dominant_period_s", "water_temp_f", "wind_speed_kt", "pressure_inhg"
            ]
            if not any(isinstance(observation.get(field), (int, float)) for field in useful_fields):
                continue
            wave_height = observation.get("wave_height_ft")
            wave_period = observation.get("dominant_period_s")
            if isinstance(wave_height, (int, float)):
                value = f"{wave_height:.1f} ft"
                if isinstance(wave_period, (int, float)):
                    value += f" @ {wave_period:.0f}s"
            else:
                value = "Observation available"
            return {
                **observation,
                "label": "NDBC Buoy / Coastal Station",
                "value": value,
                "detail": observation.get("observed_at") or "Latest NDBC observation",
                "station": station.get("name") or station_id,
                "station_id": station_id,
                "distance_miles": distance,
                "station_url": NDBC_STATION_URL_TEMPLATE.format(station_id=station_id),
                "description": "Nearest active NDBC station with usable real-time observations.",
            }
        return {
            "label": "NDBC Buoy / Coastal Station",
            "value": "Unavailable",
            "detail": "No nearby active NDBC station returned usable real-time observations.",
            "station": "",
            "distance_miles": None,
            "station_url": "https://www.ndbc.noaa.gov/obs.shtml",
        }

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
        nearest["ndbc"] = self.fetch_nearest_ndbc_data(lat, lon)
        return nearest
