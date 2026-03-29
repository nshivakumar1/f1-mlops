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
from datetime import datetime, timezone, timedelta
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


def _get(endpoint: str, params: dict, since: str = None, _retry: bool = True) -> list:
    """
    Authenticated GET → OpenF1 API. Returns parsed JSON list.
    - since: optional ISO timestamp appended as &date>={since} (avoids URL-encoding the > char)
    - 401: force-refreshes token and retries once
    - 404: returns [] (OpenF1 returns 404 for empty result sets)
    - 5xx: retries once after 2s backoff
    """
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE_URL}/{endpoint}?{qs}"
    if since:
        url += f"&date>={since}"
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
            return _get(endpoint, params, since=since, _retry=False)
        if e.code == 404:
            return []
        if e.code == 429 and _retry:
            # OpenF1 rate limit: 6 req/s — back off and retry once
            logger.warning(f"OpenF1 429 rate-limit on {endpoint}, backing off 1.5s")
            time.sleep(1.5)
            return _get(endpoint, params, since=since, _retry=False)
        if e.code >= 500 and _retry:
            logger.warning(f"OpenF1 {e.code} on {endpoint}, retrying in 2s")
            time.sleep(2)
            return _get(endpoint, params, since=since, _retry=False)
        body = e.read().decode(errors="replace")[:300]
        logger.error(f"HTTPError {e.code} GET {url} — body: {body}")
        raise
    except Exception as e:
        if _retry:
            logger.warning(f"OpenF1 request error on {endpoint}: {e}, retrying in 2s")
            time.sleep(2)
            return _get(endpoint, params, since=since, _retry=False)
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
    now = datetime.now(timezone.utc)
    sessions = _get("sessions", {"year": now.year})
    now_iso = now.strftime("%Y-%m-%dT%H:%M")
    started = [s for s in sessions if s.get("date_start", "") <= now_iso]
    return started[-1] if started else (sessions[-1] if sessions else {})


def fetch_all_session_data(session_key: str) -> dict:
    """
    Parallel-fetch all live telemetry endpoints for a session (7 concurrent calls).

    Endpoints used:
      stints       — tyre compound, lap_start, lap_end, stint_number
      intervals    — gap_to_leader, interval to car ahead
      laps         — per-lap sector times, lap durations
      weather      — air/track temp, rainfall, wind speed/direction, humidity, pressure
      race_control — safety car, VSC, flags, DRS zones, sector yellow flags
      pit          — pit stop records: lap_number, pit_duration, pit_out_lap
      car_data     — live telemetry (speed, throttle, brake, DRS, gear, RPM) — last 45s only

    Returns dicts keyed by driver_number for O(1) per-driver lookup.
    car_data returns only the single most-recent record per driver (high-frequency feed).
    """
    recent_45s = (datetime.now(timezone.utc) - timedelta(seconds=45)).strftime("%Y-%m-%dT%H:%M:%S")

    tasks = {
        "stints":       ("stints",       {"session_key": session_key}, None),
        "intervals":    ("intervals",    {"session_key": session_key}, None),
        "laps":         ("laps",         {"session_key": session_key}, None),
        "weather":      ("weather",      {"session_key": session_key}, None),
        "race_control": ("race_control", {"session_key": session_key}, None),
        "pit":          ("pit",          {"session_key": session_key}, None),
        "car_data":     ("car_data",     {"session_key": session_key}, recent_45s),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:  # OpenF1 limit: 6 req/s; 5 workers + retries stays safe
        futures = {
            pool.submit(_get, endpoint, params, since): key
            for key, (endpoint, params, since) in tasks.items()
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.error(f"fetch_all_session_data: {key} failed: {e}")
                results[key] = []

    def _group(records: list) -> dict:
        """Group records by driver_number, preserving all records per driver."""
        out: dict = {}
        for r in records:
            dn = r.get("driver_number")
            if dn is not None:
                out.setdefault(dn, []).append(r)
        return out

    def _group_latest(records: list) -> dict:
        """Keep only the most-recent record per driver (for high-frequency feeds like car_data)."""
        out: dict = {}
        for r in records:
            dn = r.get("driver_number")
            if dn is not None:
                if dn not in out or r.get("date", "") > out[dn].get("date", ""):
                    out[dn] = r
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
        "pit":          _group(results.get("pit", [])),
        "car_data":     _group_latest(results.get("car_data", [])),
    }


def build_feature_vector(driver_number: int, session_data: dict) -> Optional[dict]:
    """
    Build the 11-feature vector from pre-fetched session data.
    Also returns enriched metadata from pit and car_data endpoints.

    Features (in order — must match model training):
      [0]  tyre_age              — laps on current stint
      [1]  stint_number          — current stint number
      [2]  gap_to_leader         — seconds behind leader
      [3]  air_temperature       — °C
      [4]  track_temperature     — °C
      [5]  rainfall              — 1 if raining, 0 if dry
      [6]  sector_delta          — recent sector 1 vs 3-lap avg
      [7]  tyre_age_sq           — tyre_age²
      [8]  heat_deg_interaction  — track_temp × tyre_age / 100
      [9]  wet_stint             — rainfall × stint_number
      [10] abs_sector_delta      — |sector_delta|

    Extra metadata (not model inputs):
      lap_number        — current race lap
      pits_completed    — number of pit stops taken so far
      last_pit_duration — duration of most recent pit stop (seconds), or None
      drs_active        — whether DRS was open on the last telemetry sample
      speed             — speed in km/h at last telemetry sample
      throttle          — throttle position 0–100 at last telemetry sample
      brake             — brake pressure 0–100 at last telemetry sample
      gear              — current gear at last telemetry sample
    """
    try:
        stints = session_data["stints"].get(driver_number, [])
        intervals = session_data["intervals"].get(driver_number, [])
        all_laps = session_data["laps"].get(driver_number, [])
        laps = all_laps[-4:]  # last 4 laps only used for sector_delta
        weather = session_data["weather"]
        pits = session_data["pit"].get(driver_number, [])
        car = session_data["car_data"].get(driver_number, {})
    except Exception as e:
        logger.warning(f"build_feature_vector driver={driver_number}: {type(e).__name__}: {e}")
        return None

    # ── Feature 0 & 1: tyre_age and stint_number ─────────────────────────────
    current_stint = stints[-1] if stints else {}
    lap_start = current_stint.get("lap_start", 0)
    lap_end = current_stint.get("lap_end")
    if lap_end:
        tyre_age = lap_end - lap_start
    else:
        laps_in_stint = [l for l in all_laps if (l.get("lap_number") or 0) >= lap_start]
        tyre_age = len(laps_in_stint) if laps_in_stint else len(all_laps)
    stint_number = current_stint.get("stint_number", 1)

    # ── Feature 2: gap_to_leader ─────────────────────────────────────────────
    latest_interval = intervals[-1] if intervals else {}
    gap_raw = latest_interval.get("gap_to_leader", 0)
    try:
        gap_to_leader = float(str(gap_raw).replace("+", "")) if gap_raw else 0.0
    except (ValueError, TypeError):
        gap_to_leader = 0.0

    # ── Features 3 & 4: temperatures ─────────────────────────────────────────
    air_temperature = float(weather.get("air_temperature", 25.0))
    track_temperature = float(weather.get("track_temperature", 35.0))

    # ── Feature 5: rainfall ───────────────────────────────────────────────────
    rainfall = 1 if weather.get("rainfall", False) else 0

    # ── Feature 6: sector_delta ───────────────────────────────────────────────
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

    # ── Derived features (required by model — must match training) ────────────
    tyre_age_sq = tyre_age ** 2
    heat_deg_interaction = track_temperature * tyre_age / 100.0
    wet_stint = rainfall * stint_number
    abs_sector_delta = abs(sector_delta)

    # ── Extra metadata from pit endpoint ─────────────────────────────────────
    # pit records: each entry is one pit stop (lap_number, pit_duration, pit_out_lap)
    pit_stops = [p for p in pits if not p.get("pit_out_lap", False)]
    pits_completed = len(pit_stops)
    last_pit = pit_stops[-1] if pit_stops else {}
    last_pit_duration = last_pit.get("pit_duration")  # seconds, float or None
    last_pit_lap = last_pit.get("lap_number")         # lap number of last stop

    # ── Extra metadata from car_data endpoint ────────────────────────────────
    # car_data at ~3.7Hz — we fetch only the last 45s and take the latest entry
    drs_active = car.get("drs", 0) >= 10   # DRS values: 0=off, 10/12/14=open
    speed = car.get("speed", 0)            # km/h
    throttle = car.get("throttle", 0)      # 0–100
    brake = car.get("brake", 0)            # 0–100
    gear = car.get("n_gear", 0)            # 0–8

    # ── Current lap number ────────────────────────────────────────────────────
    lap_number = all_laps[-1].get("lap_number", 0) if all_laps else 0

    driver_info = DRIVER_GRID.get(driver_number, {})

    return {
        "driver_number": driver_number,
        "driver_name": driver_info.get("name", f"Driver #{driver_number}"),
        "team": driver_info.get("team", "Unknown"),
        "session_key": session_data.get("session_key", "unknown"),
        "tyre_compound": current_stint.get("compound", "UNKNOWN"),
        "lap_number": lap_number,
        "pits_completed": pits_completed,
        "last_pit_duration": round(last_pit_duration, 2) if last_pit_duration else None,
        "last_pit_lap": last_pit_lap,
        "drs_active": drs_active,
        "speed": speed,
        "throttle": throttle,
        "brake": brake,
        "gear": gear,
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
