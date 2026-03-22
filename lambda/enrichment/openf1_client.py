"""
OpenF1 API client — wraps all 20 live metrics endpoints.
Uses OAuth2 bearer token auth during live sessions.
Base URL: https://api.openf1.org/v1
Credentials stored in Secrets Manager: f1-mlops/openf1-credentials
  {"username": "email@example.com", "password": "yourpassword"}
"""
import json
import logging
import os
import time
import urllib.request
import urllib.parse
import urllib.error
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openf1.org/v1"
_TOKEN_URL = "https://api.openf1.org/token"
_SECRET_NAME = "f1-mlops/openf1-credentials"
_AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

# Module-level caches — survive warm Lambda invocations
_token_cache: dict = {"access_token": None, "expires_at": 0.0}
_weather_cache: dict = {}        # session_key → {"data": ..., "fetched_at": float}
_WEATHER_TTL = 300               # refresh weather every 5 min (catches mid-race rain)

_sm = boto3.client("secretsmanager", region_name=_AWS_REGION)


def _get_auth_token(force_refresh: bool = False) -> str:
    """Return a valid OAuth2 bearer token, refreshing if needed."""
    now = time.time()
    if not force_refresh and _token_cache["access_token"] and now < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    secret = json.loads(_sm.get_secret_value(SecretId=_SECRET_NAME)["SecretString"])

    body = urllib.parse.urlencode({
        "grant_type": "password",
        "username": secret["username"],
        "password": secret["password"],
    }).encode()
    req = urllib.request.Request(
        _TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        token_data = json.loads(resp.read().decode())

    _token_cache["access_token"] = token_data["access_token"]
    # Refresh 60s before actual expiry to avoid mid-invocation expiry
    _token_cache["expires_at"] = now + int(token_data.get("expires_in", 3600)) - 60
    return _token_cache["access_token"]


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


def _get(endpoint: str, params: dict, _retry: bool = True) -> list:
    """
    Authenticated GET → OpenF1 API. Returns parsed JSON list.
    - 401: force-refreshes token and retries once
    - 404: returns [] (OpenF1 returns 404 for empty result sets)
    - 5xx: retries once after 2s backoff
    """
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE_URL}/{endpoint}?{qs}"
    token = _get_auth_token()
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401 and _retry:
            _get_auth_token(force_refresh=True)
            return _get(endpoint, params, _retry=False)
        if e.code == 404:
            # OpenF1 returns 404 for empty result sets — not a real error
            return []
        if e.code >= 500 and _retry:
            # Transient server error — wait and retry once
            logger.warning(f"OpenF1 {e.code} on {endpoint}, retrying in 2s")
            time.sleep(2)
            return _get(endpoint, params, _retry=False)
        body = e.read().decode(errors="replace")[:300]
        logger.error(f"HTTPError {e.code} GET {url} — body: {body}")
        raise
    except Exception as e:
        if _retry:
            logger.warning(f"OpenF1 request error on {endpoint}: {e}, retrying in 2s")
            time.sleep(2)
            return _get(endpoint, params, _retry=False)
        raise


def get_weather(session_key: str) -> dict:
    """
    Track temp, air temp, rainfall, wind. Latest reading.
    Cached per session with 5-minute TTL to catch mid-race rain.
    """
    now = time.time()
    cached = _weather_cache.get(session_key)
    if cached and now - cached["fetched_at"] < _WEATHER_TTL:
        return cached["data"]
    records = _get("weather", {"session_key": session_key})
    result = records[-1] if records else {}
    _weather_cache[session_key] = {"data": result, "fetched_at": now}
    return result


def get_race_control(session_key: str) -> list:
    """Safety car, VSC, flag messages."""
    return _get("race_control", {"session_key": session_key})


def get_latest_session() -> dict:
    """Returns the most recent session that has already started."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    sessions = _get("sessions", {"year": now.year})
    now_iso = now.strftime("%Y-%m-%dT%H:%M")
    started = [s for s in sessions if s.get("date_start", "") <= now_iso]
    return started[-1] if started else (sessions[-1] if sessions else {})


def fetch_all_session_data(session_key: str) -> dict:
    """
    Parallel-fetch stints, intervals, laps, weather, and race_control
    for ALL drivers in a single round-trip (5 concurrent calls).

    Previously sequential (3 calls × ~700ms = ~2.1s).
    Now concurrent: all 5 calls complete in ~max(individual latencies) ≈ 700ms.

    Returns dicts keyed by driver_number for O(1) per-driver lookup.
    """
    tasks = {
        "stints":        ("stints",        {"session_key": session_key}),
        "intervals":     ("intervals",     {"session_key": session_key}),
        "laps":          ("laps",          {"session_key": session_key}),
        "weather":       ("weather",       {"session_key": session_key}),
        "race_control":  ("race_control",  {"session_key": session_key}),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_get, endpoint, params): key
            for key, (endpoint, params) in tasks.items()
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.error(f"fetch_all_session_data: {key} failed: {e}")
                results[key] = []

    def _group(records: list) -> dict:
        out: dict = {}
        for r in records:
            dn = r.get("driver_number")
            if dn is not None:
                out.setdefault(dn, []).append(r)
        return out

    # Update weather cache with fresh data
    weather_records = results.get("weather", [])
    weather = weather_records[-1] if weather_records else {}
    _weather_cache[session_key] = {"data": weather, "fetched_at": time.time()}

    return {
        "stints":       _group(results.get("stints", [])),
        "intervals":    _group(results.get("intervals", [])),
        "laps":         _group(results.get("laps", [])),
        "weather":      weather,
        "race_control": results.get("race_control", []),
    }


def build_feature_vector(driver_number: int, session_data: dict) -> Optional[dict]:
    """
    Build the 11-feature vector from pre-fetched session data.

    Features (in order):
      [0]  tyre_age              — laps on current stint
      [1]  stint_number          — current stint number
      [2]  gap_to_leader         — seconds behind leader
      [3]  air_temperature       — °C
      [4]  track_temperature     — °C
      [5]  rainfall              — 1 if raining, 0 if dry
      [6]  sector_delta          — recent sector 1 vs 3-lap avg
      [7]  tyre_age_sq           — tyre_age²
      [8]  heat_deg_interaction  — track_temp × tyre_age
      [9]  wet_stint             — rainfall × stint_number
      [10] abs_sector_delta      — |sector_delta|
    """
    try:
        stints = session_data["stints"].get(driver_number, [])
        intervals = session_data["intervals"].get(driver_number, [])
        laps = session_data["laps"].get(driver_number, [])[-4:]
        weather = session_data["weather"]
    except Exception as e:
        logger.warning(f"build_feature_vector driver={driver_number}: {type(e).__name__}: {e}")
        return None

    # Feature 0 & 1: tyre_age and stint_number
    current_stint = stints[-1] if stints else {}
    lap_start = current_stint.get("lap_start", 0)
    # lap_end is None for an ongoing stint — compute from fresh laps data so
    # tyre_age stays accurate even when stints come from the S3 fallback cache.
    lap_end = current_stint.get("lap_end")
    if lap_end:
        tyre_age = lap_end - lap_start
    else:
        # Count laps completed since this stint started using fresh lap records
        laps_in_stint = [l for l in laps if (l.get("lap_number") or 0) >= lap_start]
        tyre_age = len(laps_in_stint) if laps_in_stint else len(laps)
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

    # Derived features (required by model — must match training)
    tyre_age_sq = tyre_age ** 2
    heat_deg_interaction = track_temperature * tyre_age / 100.0
    wet_stint = rainfall * stint_number
    abs_sector_delta = abs(sector_delta)

    driver_info = DRIVER_GRID.get(driver_number, {})

    return {
        "driver_number": driver_number,
        "driver_name": driver_info.get("name", f"Driver #{driver_number}"),
        "team": driver_info.get("team", "Unknown"),
        "session_key": session_data.get("session_key", "unknown"),
        "tyre_compound": current_stint.get("compound", "UNKNOWN"),
        "features": [
            tyre_age,
            stint_number,
            gap_to_leader,
            air_temperature,
            track_temperature,
            rainfall,
            sector_delta,
            tyre_age_sq,
            heat_deg_interaction,
            wet_stint,
            abs_sector_delta,
        ],
        "feature_names": [
            "tyre_age",
            "stint_number",
            "gap_to_leader",
            "air_temperature",
            "track_temperature",
            "rainfall",
            "sector_delta",
            "tyre_age_sq",
            "heat_deg_interaction",
            "wet_stint",
            "abs_sector_delta",
        ],
    }
