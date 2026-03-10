"""
OpenF1 API client — wraps all 20 live metrics endpoints.
Free, no authentication required.
Base URL: https://api.openf1.org/v1
"""
import json
import urllib.request
import urllib.parse
from typing import Optional

BASE_URL = "https://api.openf1.org/v1"

# 2026 full driver grid: driver_number → metadata
DRIVER_GRID = {
    1:  {"name": "Lando Norris",      "team": "McLaren",       "nationality": "British"},
    4:  {"name": "Oscar Piastri",     "team": "McLaren",       "nationality": "Australian"},
    16: {"name": "Charles Leclerc",   "team": "Ferrari",       "nationality": "Monegasque"},
    44: {"name": "Lewis Hamilton",    "team": "Ferrari",       "nationality": "British"},
    63: {"name": "George Russell",    "team": "Mercedes",      "nationality": "British"},
    12: {"name": "Kimi Antonelli",    "team": "Mercedes",      "nationality": "Italian"},
    3:  {"name": "Max Verstappen",    "team": "Red Bull",      "nationality": "Dutch"},
    6:  {"name": "Isack Hadjar",      "team": "Red Bull",      "nationality": "French"},
    55: {"name": "Carlos Sainz",      "team": "Williams",      "nationality": "Spanish"},
    23: {"name": "Alexander Albon",   "team": "Williams",      "nationality": "Thai"},
    14: {"name": "Fernando Alonso",   "team": "Aston Martin",  "nationality": "Spanish"},
    18: {"name": "Lance Stroll",      "team": "Aston Martin",  "nationality": "Canadian"},
    10: {"name": "Pierre Gasly",      "team": "Alpine",        "nationality": "French"},
    43: {"name": "Franco Colapinto",  "team": "Alpine",        "nationality": "Argentine"},
    31: {"name": "Esteban Ocon",      "team": "Haas",          "nationality": "French"},
    87: {"name": "Oliver Bearman",    "team": "Haas",          "nationality": "British"},
    30: {"name": "Liam Lawson",       "team": "Racing Bulls",  "nationality": "N. Zealander"},
    41: {"name": "Arvid Lindblad",    "team": "Racing Bulls",  "nationality": "British"},
    27: {"name": "Nico Hulkenberg",   "team": "Audi",          "nationality": "German"},
    5:  {"name": "Gabriel Bortoleto", "team": "Audi",          "nationality": "Brazilian"},
    11: {"name": "Sergio Perez",      "team": "Cadillac",      "nationality": "Mexican"},
    77: {"name": "Valtteri Bottas",   "team": "Cadillac",      "nationality": "Finnish"},
}

ALL_DRIVER_NUMBERS = list(DRIVER_GRID.keys())


def _get(endpoint: str, params: dict) -> list:
    """Make GET request to OpenF1 API, return parsed JSON list."""
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE_URL}/{endpoint}?{qs}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def get_car_data(session_key: str, driver_number: int, limit: int = 5) -> list:
    """Speed, throttle, brake, RPM, gear, DRS at 3.7 Hz."""
    return _get("car_data", {
        "session_key": session_key,
        "driver_number": driver_number,
    })[-limit:]


def get_intervals(session_key: str, driver_number: int) -> list:
    """Gap to leader and interval ahead, per lap."""
    return _get("intervals", {
        "session_key": session_key,
        "driver_number": driver_number,
    })


def get_stints(session_key: str, driver_number: int) -> list:
    """Tyre compound, age, stint number."""
    return _get("stints", {
        "session_key": session_key,
        "driver_number": driver_number,
    })


def get_weather(session_key: str) -> dict:
    """Track temp, air temp, rainfall, wind. Latest reading."""
    records = _get("weather", {"session_key": session_key})
    return records[-1] if records else {}


def get_laps(session_key: str, driver_number: int, last_n: int = 5) -> list:
    """Lap duration, sector times. Last N laps."""
    return _get("laps", {
        "session_key": session_key,
        "driver_number": driver_number,
    })[-last_n:]


def get_position(session_key: str, driver_number: int) -> dict:
    """Current race position."""
    records = _get("position", {
        "session_key": session_key,
        "driver_number": driver_number,
    })
    return records[-1] if records else {}


def get_race_control(session_key: str) -> list:
    """Safety car, VSC, flag messages."""
    return _get("race_control", {"session_key": session_key})


def get_latest_session() -> dict:
    """Returns the most recent session from OpenF1."""
    sessions = _get("sessions", {"year": 2026})
    return sessions[-1] if sessions else {}


def build_feature_vector(session_key: str, driver_number: int) -> Optional[dict]:
    """
    Builds the 7-feature vector for the SageMaker pitstop prediction endpoint.

    Features (in order):
      [0] tyre_age       — laps on current stint
      [1] stint_number   — current stint number
      [2] gap_to_leader  — seconds behind leader
      [3] air_temperature — °C
      [4] track_temperature — °C
      [5] rainfall       — 1 if raining, 0 if dry
      [6] sector_delta   — current sector time vs driver avg of last 3 laps
    """
    try:
        stints = get_stints(session_key, driver_number)
        intervals = get_intervals(session_key, driver_number)
        weather = get_weather(session_key)
        laps = get_laps(session_key, driver_number, last_n=4)
    except Exception as e:
        return None

    # Feature 0 & 1: tyre_age and stint_number
    current_stint = stints[-1] if stints else {}
    lap_start = current_stint.get("lap_start", 0)
    lap_end = current_stint.get("lap_end") or (lap_start + len(laps))
    tyre_age = lap_end - lap_start
    stint_number = current_stint.get("stint_number", 1)

    # Feature 2: gap_to_leader
    latest_interval = intervals[-1] if intervals else {}
    gap_raw = latest_interval.get("gap_to_leader", 0)
    try:
        gap_to_leader = float(str(gap_raw).replace("+", "")) if gap_raw else 0.0
    except (ValueError, TypeError):
        gap_to_leader = 0.0

    # Features 3 & 4: temperatures
    air_temperature = float(weather.get("air_temperature", 25.0))
    track_temperature = float(weather.get("track_temperature", 35.0))

    # Feature 5: rainfall
    rainfall = 1 if weather.get("rainfall", False) else 0

    # Feature 6: sector_delta
    # Compare last lap sector 1 to avg of previous 3 laps sector 1
    sector_delta = 0.0
    if len(laps) >= 2:
        try:
            recent_sector = laps[-1].get("duration_sector_1") or 0
            prev_sectors = [
                lap.get("duration_sector_1") or 0
                for lap in laps[:-1]
                if lap.get("duration_sector_1")
            ]
            if prev_sectors and recent_sector:
                avg_prev = sum(prev_sectors) / len(prev_sectors)
                sector_delta = float(recent_sector) - avg_prev
        except (TypeError, ValueError):
            sector_delta = 0.0

    driver_info = DRIVER_GRID.get(driver_number, {})

    return {
        "driver_number": driver_number,
        "driver_name": driver_info.get("name", f"Driver #{driver_number}"),
        "team": driver_info.get("team", "Unknown"),
        "session_key": session_key,
        "tyre_compound": current_stint.get("compound", "UNKNOWN"),
        "features": [
            tyre_age,
            stint_number,
            gap_to_leader,
            air_temperature,
            track_temperature,
            rainfall,
            sector_delta,
        ],
        "feature_names": [
            "tyre_age",
            "stint_number",
            "gap_to_leader",
            "air_temperature",
            "track_temperature",
            "rainfall",
            "sector_delta",
        ],
    }
