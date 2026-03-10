"""
Seed Historical F1 Data to S3
Fetches past sessions from OpenF1 API and uploads raw data to S3.
Run once before the first model training to bootstrap training data.
Usage: python scripts/seed_historical_data.py --bucket f1-mlops-data-297997106614 --year 2024
"""
import argparse
import json
import os
import sys
import time
import boto3
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BASE_URL = "https://api.openf1.org/v1"

# 2026 driver grid — same as enrichment Lambda
DRIVER_NUMBERS = [1, 4, 16, 44, 63, 12, 3, 6, 55, 23, 14, 18, 10, 43, 31, 87, 30, 41, 27, 5, 11, 77]


def openf1_get(endpoint: str, params: dict) -> list:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE_URL}/{endpoint}?{qs}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fetch_sessions(year: int) -> list:
    """Get all race/qualifying sessions for a given year."""
    sessions = openf1_get("sessions", {"year": year, "session_type": "Race"})
    sessions += openf1_get("sessions", {"year": year, "session_type": "Qualifying"})
    sessions += openf1_get("sessions", {"year": year, "session_type": "Sprint"})
    print(f"Found {len(sessions)} sessions for {year}")
    return sessions


def fetch_session_data(session_key: str, driver_numbers: list) -> dict:
    """Fetch all metrics for a session."""
    print(f"  Fetching session {session_key}...")
    data = {
        "session_key": session_key,
        "weather": [],
        "race_control": [],
        "drivers": {},
    }

    # Weather — one fetch per session
    try:
        data["weather"] = openf1_get("weather", {"session_key": session_key})
    except Exception as e:
        print(f"    Weather failed: {e}")

    # Race control messages
    try:
        data["race_control"] = openf1_get("race_control", {"session_key": session_key})
    except Exception as e:
        print(f"    Race control failed: {e}")

    for driver_number in driver_numbers:
        driver_data = {}
        try:
            driver_data["laps"] = openf1_get("laps", {"session_key": session_key, "driver_number": driver_number})
            driver_data["stints"] = openf1_get("stints", {"session_key": session_key, "driver_number": driver_number})
            driver_data["intervals"] = openf1_get("intervals", {"session_key": session_key, "driver_number": driver_number})
            driver_data["position"] = openf1_get("position", {"session_key": session_key, "driver_number": driver_number})
            driver_data["pit"] = openf1_get("pit", {"session_key": session_key, "driver_number": driver_number})
            if driver_data["laps"]:
                data["drivers"][str(driver_number)] = driver_data
        except Exception as e:
            print(f"    Driver {driver_number} failed: {e}")

        time.sleep(0.1)  # Rate limiting

    return data


def build_training_rows(session_data: dict) -> list:
    """
    Convert raw session data to flat training rows.
    One row per driver per lap with all features and target label.
    """
    rows = []
    session_key = session_data["session_key"]

    # Build weather lookup by lap (approx by timestamp)
    weather_records = session_data.get("weather", [])
    latest_weather = weather_records[-1] if weather_records else {}
    air_temp = float(latest_weather.get("air_temperature", 25))
    track_temp = float(latest_weather.get("track_temperature", 35))
    rainfall = 1 if latest_weather.get("rainfall", False) else 0

    # Safety car events
    sc_laps = set()
    for msg in session_data.get("race_control", []):
        text = msg.get("message", "").upper()
        if "SAFETY CAR" in text or "VIRTUAL SAFETY CAR" in text:
            lap_num = msg.get("lap_number")
            if lap_num:
                for offset in range(5):
                    sc_laps.add(lap_num + offset)

    for driver_str, driver_data in session_data.get("drivers", {}).items():
        driver_number = int(driver_str)
        laps = driver_data.get("laps", [])
        stints = driver_data.get("stints", [])
        intervals = driver_data.get("intervals", [])
        pit_records = driver_data.get("pit", [])

        if not laps:
            continue

        # Build pit lap set
        pit_laps = {p["lap_number"] for p in pit_records if p.get("lap_number")}

        # Build interval lookup
        interval_by_lap = {
            iv.get("lap_number"): iv.get("gap_to_leader", 0)
            for iv in intervals if iv.get("lap_number")
        }

        # Build stint lookup
        def get_stint_for_lap(lap_num):
            for s in stints:
                if s.get("lap_start", 0) <= lap_num <= s.get("lap_end", 9999):
                    return s
            return {}

        total_laps = len(laps)
        for i, lap in enumerate(laps):
            lap_num = lap.get("lap_number", i + 1)
            stint = get_stint_for_lap(lap_num)
            lap_start = stint.get("lap_start", 1)
            tyre_age = max(0, lap_num - lap_start)
            stint_number = stint.get("stint_number", 1)
            tyre_compound = stint.get("compound", "UNKNOWN")

            # Gap to leader
            gap_raw = interval_by_lap.get(lap_num, 0)
            try:
                gap_to_leader = float(str(gap_raw).replace("+", "")) if gap_raw else 0.0
            except (ValueError, TypeError):
                gap_to_leader = 0.0

            # Sector delta vs last 3 laps
            sector_delta = 0.0
            if i >= 3:
                current_s1 = lap.get("duration_sector_1") or 0
                prev_s1 = [l.get("duration_sector_1") or 0 for l in laps[max(0, i-3):i] if l.get("duration_sector_1")]
                if prev_s1 and current_s1:
                    sector_delta = float(current_s1) - (sum(prev_s1) / len(prev_s1))

            # Target: will this driver pit in next 3 laps?
            next_laps_nums = range(lap_num + 1, lap_num + 4)
            pitstop_within_3 = 1 if any(n in pit_laps for n in next_laps_nums) else 0

            # Safety car target
            sc_within_5 = 1 if any(lap_num + k in sc_laps for k in range(1, 6)) else 0

            rows.append({
                "session_key": session_key,
                "driver_number": driver_number,
                "lap_number": lap_num,
                "event_time": lap.get("date_start", datetime.now(timezone.utc).isoformat()),
                "tyre_age": tyre_age,
                "stint_number": stint_number,
                "tyre_compound": tyre_compound,
                "gap_to_leader": gap_to_leader,
                "air_temperature": air_temp,
                "track_temperature": track_temp,
                "rainfall": rainfall,
                "sector_delta": round(sector_delta, 3),
                "lap_duration": lap.get("lap_duration"),
                "did_pit": 1 if lap_num in pit_laps else 0,
                "pitstop_within_3_laps": pitstop_within_3,
                "safety_car_within_5_laps": sc_within_5,
                "total_laps": total_laps,
            })

    return rows


def main():
    parser = argparse.ArgumentParser(description="Seed historical F1 data to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--year", type=int, default=2024, help="Season year to fetch")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--max-sessions", type=int, default=10, help="Limit sessions (API rate limiting)")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    all_rows = []

    sessions = fetch_sessions(args.year)[:args.max_sessions]
    print(f"Processing {len(sessions)} sessions...")

    for session in sessions:
        session_key = str(session.get("session_key", ""))
        if not session_key:
            continue

        try:
            session_data = fetch_session_data(session_key, DRIVER_NUMBERS)
            rows = build_training_rows(session_data)
            all_rows.extend(rows)

            # Upload raw session data to S3
            raw_key = f"raw/year={args.year}/session_{session_key}.json"
            s3.put_object(
                Bucket=args.bucket,
                Key=raw_key,
                Body=json.dumps(session_data),
                ContentType="application/json",
            )
            print(f"  Uploaded {len(rows)} rows → s3://{args.bucket}/{raw_key}")
        except Exception as e:
            print(f"  Session {session_key} failed: {e}")
        time.sleep(1)

    # Upload consolidated training CSV
    if all_rows:
        import csv
        import io
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=all_rows[0].keys())
        writer.writeheader()
        writer.writerows(all_rows)

        csv_key = f"processed/pitstop/historical_{args.year}.csv"
        s3.put_object(
            Bucket=args.bucket,
            Key=csv_key,
            Body=output.getvalue().encode(),
            ContentType="text/csv",
        )
        print(f"\nTotal rows: {len(all_rows)}")
        print(f"Uploaded training data → s3://{args.bucket}/{csv_key}")
    else:
        print("No rows generated — check API availability")


if __name__ == "__main__":
    main()
