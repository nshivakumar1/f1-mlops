"""
SageMaker Training Script — Final Position Predictor
Algorithm: Random Forest Regressor
Target: final_position (1–22)
Target metric: RMSE < 2.5 positions
Features: grid_pos, qualifying_delta, pit_count, stint_strategy, circuit_type, live race state
"""
import argparse
import os
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import LabelEncoder

FEATURE_COLS = [
    "grid_position",
    "qualifying_delta_to_pole",
    "pit_count",
    "avg_stint_length",
    "circuit_type_encoded",
    "team_performance_score",
    "tyre_strategy_encoded",
    "weather_impact_score",
    "current_position",      # live race position (1–22), derived from gap ranking
    "gap_to_leader",         # seconds behind leader (0.0 for leader)
    "lap_fraction",          # lap_number / total_laps (0.0–1.0)
    "safety_car_active",     # 1 if SC/VSC active, 0 if not
]
TARGET_COL = "final_position"
RMSE_THRESHOLD = 2.5


def load_data(data_dir: str) -> pd.DataFrame:
    dfs = []
    for fname in os.listdir(data_dir):
        if fname.endswith(".parquet"):
            dfs.append(pd.read_parquet(os.path.join(data_dir, fname)))
        elif fname.endswith(".csv"):
            dfs.append(pd.read_csv(os.path.join(data_dir, fname)))
    return pd.concat(dfs, ignore_index=True)


def encode_features(df: pd.DataFrame) -> pd.DataFrame:
    """Encode categorical features."""
    circuit_encoder = LabelEncoder()
    df["circuit_type_encoded"] = circuit_encoder.fit_transform(
        df.get("circuit_type", pd.Series(["street"] * len(df)))
    )

    tyre_strategy_map = {"SOFT-MEDIUM": 0, "SOFT-HARD": 1, "MEDIUM-HARD": 2, "ONE-STOP": 3, "TWO-STOP": 4}
    df["tyre_strategy_encoded"] = df.get("tyre_strategy", pd.Series(["TWO-STOP"] * len(df))).map(tyre_strategy_map).fillna(4)

    # Team performance score based on constructor championship points
    team_scores = {
        "McLaren": 0.95, "Ferrari": 0.90, "Mercedes": 0.85, "Red Bull": 0.88,
        "Williams": 0.65, "Aston Martin": 0.70, "Alpine": 0.60, "Haas": 0.55,
        "Racing Bulls": 0.62, "Audi": 0.50, "Cadillac": 0.45,
    }
    df["team_performance_score"] = df.get("team", pd.Series(["McLaren"] * len(df))).map(team_scores).fillna(0.5)

    # Live features — fill with sensible defaults when not present in historical data
    if "current_position" not in df.columns:
        df["current_position"] = df.get("grid_position", pd.Series([10] * len(df)))
    if "gap_to_leader" not in df.columns:
        df["gap_to_leader"] = 0
    if "lap_fraction" not in df.columns:
        df["lap_fraction"] = 0.5
    if "safety_car_active" not in df.columns:
        df["safety_car_active"] = 0

    return df


def train(args):
    print("=== F1 Final Position Predictor — Random Forest Training ===")

    df = load_data(args.data_dir)
    df = encode_features(df)

    # Fill missing features
    for col in FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0

    X = df[FEATURE_COLS].fillna(0).values
    y = df[TARGET_COL].values

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
    print(f"Train: {len(X_train)} | Val: {len(X_val)}")

    model = RandomForestRegressor(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        min_samples_leaf=5,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_val)
    rmse = mean_squared_error(y_val, y_pred, squared=False)
    print(f"\n=== Validation Results ===")
    print(f"RMSE: {rmse:.4f} positions (threshold: {RMSE_THRESHOLD})")
    print(f"Mean Absolute Error: {np.mean(np.abs(y_pred - y_val)):.4f} positions")

    metrics = {
        "rmse": rmse,
        "rmse_threshold": RMSE_THRESHOLD,
        "approved": rmse <= RMSE_THRESHOLD,
        "n_train": len(X_train),
        "n_val": len(X_val),
    }
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "evaluation.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    model_dir = os.environ.get("SM_MODEL_DIR", args.model_dir)
    os.makedirs(model_dir, exist_ok=True)
    joblib.dump(model, os.path.join(model_dir, "rf_position.pkl"))
    with open(os.path.join(model_dir, "feature_names.json"), "w") as f:
        json.dump(FEATURE_COLS, f)

    print(f"Model saved to {model_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default=os.environ.get("SM_CHANNEL_TRAINING", "/opt/ml/input/data/training"))
    parser.add_argument("--model-dir", type=str, default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    parser.add_argument("--output-dir", type=str, default=os.environ.get("SM_OUTPUT_DATA_DIR", "/opt/ml/output/data"))
    parser.add_argument("--n-estimators", type=int, default=200)
    parser.add_argument("--max-depth", type=int, default=10)
    args = parser.parse_args()
    train(args)
