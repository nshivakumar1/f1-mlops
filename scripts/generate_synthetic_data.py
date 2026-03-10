"""
Generate synthetic F1 training data based on real race patterns.
Used to bootstrap the model when OpenF1 historical data is limited.
The distributions match real F1 race statistics.

Uploads to S3: processed/pitstop/synthetic_training.csv
"""
import csv
import io
import random
import argparse
import boto3
import numpy as np

random.seed(42)
np.random.seed(42)

CIRCUITS = ["shanghai", "monza", "spa", "silverstone", "monaco", "bahrain",
            "suzuka", "cota", "interlagos", "singapore", "zandvoort", "baku"]
COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]
TEAMS = ["McLaren", "Ferrari", "Mercedes", "Red Bull", "Williams",
         "Aston Martin", "Alpine", "Haas", "Racing Bulls", "Audi", "Cadillac"]

COMPOUND_DEG_RATE = {"SOFT": 0.08, "MEDIUM": 0.05, "HARD": 0.03}
COMPOUND_MAX_LIFE = {"SOFT": 25, "MEDIUM": 38, "HARD": 50}


def generate_race(session_id: int, total_laps: int = 57, n_drivers: int = 20) -> list:
    rows = []
    air_temp = float(np.random.uniform(18, 40))
    track_temp = air_temp + float(np.random.uniform(8, 20))
    rainfall = 1 if np.random.random() < 0.08 else 0

    for driver_num in range(1, n_drivers + 1):
        team = random.choice(TEAMS)
        stint_number = 1
        lap_in_stint = 0
        compound = np.random.choice(COMPOUNDS, p=[0.5, 0.35, 0.15])

        # Pitstop laps — typically 1-2 stops
        n_stops = np.random.choice([1, 2, 3], p=[0.25, 0.60, 0.15])
        stop_laps = sorted(np.random.choice(
            range(12, total_laps - 8), size=n_stops, replace=False
        ).tolist())
        pit_lap_set = set(stop_laps)

        # Sector times (base + noise)
        base_sector1 = float(np.random.uniform(28, 35))
        sector_history = []

        gap = float(np.random.uniform(0, 45))

        for lap in range(1, total_laps + 1):
            lap_in_stint += 1

            # Pit this lap?
            did_pit = 1 if lap in pit_lap_set else 0
            if did_pit:
                stint_number += 1
                lap_in_stint = 0
                compound = np.random.choice(COMPOUNDS, p=[0.3, 0.5, 0.2])

            # Tyre degradation effect on sector time
            deg = COMPOUND_DEG_RATE[compound]
            sector1 = base_sector1 * (1 + deg * lap_in_stint / 10) + float(np.random.normal(0, 0.3))
            sector_history.append(sector1)

            # Sector delta vs last 3 laps
            if len(sector_history) >= 4:
                prev_avg = np.mean(sector_history[-4:-1])
                sector_delta = round(sector_history[-1] - prev_avg, 3)
            else:
                sector_delta = 0.0

            # Gap evolves over lap
            gap += float(np.random.normal(0, 0.5))
            gap = max(0, min(120, gap))

            # Target: will this driver pit in the next 3 laps?
            next_3 = {lap + 1, lap + 2, lap + 3}
            pitstop_within_3 = 1 if (next_3 & pit_lap_set) else 0

            # Boost probability near natural tyre life
            max_life = COMPOUND_MAX_LIFE[compound]
            if lap_in_stint >= max_life - 3:
                pitstop_within_3 = 1

            rows.append({
                "session_key": f"synthetic_{session_id}",
                "driver_number": driver_num,
                "lap_number": lap,
                "event_time": f"2024-01-01T{lap:02d}:00:00Z",
                "tyre_age": lap_in_stint,
                "stint_number": stint_number,
                "tyre_compound": compound,
                "gap_to_leader": round(gap, 2),
                "air_temperature": round(air_temp, 1),
                "track_temperature": round(track_temp, 1),
                "rainfall": rainfall,
                "sector_delta": round(sector_delta, 3),
                "lap_duration": round(sector1 * 3.1 + float(np.random.normal(0, 0.5)), 2),
                "did_pit": did_pit,
                "pitstop_within_3_laps": pitstop_within_3,
                "safety_car_within_5_laps": 0,
                "total_laps": total_laps,
            })

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--n-races", type=int, default=50, help="Number of synthetic races to generate")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    all_rows = []
    for i in range(args.n_races):
        total_laps = random.randint(44, 72)
        rows = generate_race(session_id=i, total_laps=total_laps)
        all_rows.extend(rows)
        if (i + 1) % 10 == 0:
            print(f"Generated {i+1}/{args.n_races} races ({len(all_rows)} rows)")

    # Shuffle to prevent ordering bias
    random.shuffle(all_rows)

    # Count pitstop rate
    pit_rate = sum(r["pitstop_within_3_laps"] for r in all_rows) / len(all_rows)
    print(f"\nTotal rows: {len(all_rows)}")
    print(f"Pitstop positive rate: {pit_rate:.3f} (target ~0.12-0.18)")

    # Write CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=all_rows[0].keys())
    writer.writeheader()
    writer.writerows(all_rows)

    s3 = boto3.client("s3", region_name=args.region)
    key = "processed/pitstop/synthetic_training.csv"
    s3.put_object(
        Bucket=args.bucket,
        Key=key,
        Body=output.getvalue().encode(),
        ContentType="text/csv",
    )
    print(f"Uploaded → s3://{args.bucket}/{key}")


if __name__ == "__main__":
    main()
