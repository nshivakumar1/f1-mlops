"""
SageMaker Training Script — Safety Car Probability Predictor
Algorithm: LightGBM (binary classification)
Target: safety_car_within_5_laps (0 or 1)
Target metric: F1-Score >= 0.76
Features: lap_number, circuit_id, rainfall, gap_variance, incident_history
"""
import argparse
import os
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, classification_report
from sklearn.preprocessing import LabelEncoder
import lightgbm as lgb

FEATURE_COLS = [
    "lap_number",
    "lap_fraction",
    "circuit_id_encoded",
    "rainfall",
    "gap_variance",
    "incident_count_last_5_laps",
    "yellow_flag_count",
    "delta_to_backmarker",
    "field_compression_score",
]
TARGET_COL = "safety_car_within_5_laps"
F1_THRESHOLD = 0.76


def load_data(data_dir: str) -> pd.DataFrame:
    dfs = []
    for fname in os.listdir(data_dir):
        if fname.endswith(".parquet"):
            dfs.append(pd.read_parquet(os.path.join(data_dir, fname)))
        elif fname.endswith(".csv"):
            dfs.append(pd.read_csv(os.path.join(data_dir, fname)))
    return pd.concat(dfs, ignore_index=True)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    total_laps = df.get("total_laps", pd.Series([57] * len(df)))
    df["lap_fraction"] = df["lap_number"] / total_laps

    circuit_encoder = LabelEncoder()
    circuits = df.get("circuit_id", pd.Series(["shanghai"] * len(df)))
    df["circuit_id_encoded"] = circuit_encoder.fit_transform(circuits)

    # Gap variance: high variance = potential for incidents
    if "gap_variance" not in df.columns:
        df["gap_variance"] = np.random.uniform(0.5, 15.0, len(df))

    # Field compression: how tightly packed the field is
    if "field_compression_score" not in df.columns:
        df["field_compression_score"] = 1.0 / (df.get("gap_to_leader", pd.Series([20.0] * len(df))) + 1)

    return df


def train(args):
    print("=== F1 Safety Car Predictor — LightGBM Training ===")

    df = load_data(args.data_dir)
    df = engineer_features(df)

    for col in FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0

    X = df[FEATURE_COLS].fillna(0).values
    y = df[TARGET_COL].values

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
    print(f"Train: {len(X_train)} | Val: {len(X_val)} | SC rate: {y.mean():.3f}")

    scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)

    lgb_train = lgb.Dataset(X_train, label=y_train)
    lgb_val = lgb.Dataset(X_val, label=y_val, reference=lgb_train)

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "num_leaves": 31,
        "learning_rate": args.learning_rate,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "scale_pos_weight": scale_pos_weight,
        "verbose": -1,
        "random_state": 42,
    }

    model = lgb.train(
        params,
        lgb_train,
        num_boost_round=args.num_rounds,
        valid_sets=[lgb_val],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )

    y_pred_proba = model.predict(X_val)
    y_pred = (y_pred_proba >= 0.5).astype(int)
    f1 = f1_score(y_val, y_pred)

    print(f"\n=== Validation Results ===")
    print(f"F1-Score: {f1:.4f} (threshold: {F1_THRESHOLD})")
    print(classification_report(y_val, y_pred))

    metrics = {
        "f1_score": f1,
        "f1_threshold": F1_THRESHOLD,
        "approved": f1 >= F1_THRESHOLD,
        "n_train": len(X_train),
        "n_val": len(X_val),
    }
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "evaluation.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    model_dir = os.environ.get("SM_MODEL_DIR", args.model_dir)
    os.makedirs(model_dir, exist_ok=True)
    model.save_model(os.path.join(model_dir, "lgb_safety_car.txt"))
    with open(os.path.join(model_dir, "feature_names.json"), "w") as f:
        json.dump(FEATURE_COLS, f)

    print(f"Model saved to {model_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default=os.environ.get("SM_CHANNEL_TRAINING", "/opt/ml/input/data/training"))
    parser.add_argument("--model-dir", type=str, default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    parser.add_argument("--output-dir", type=str, default=os.environ.get("SM_OUTPUT_DATA_DIR", "/opt/ml/output/data"))
    parser.add_argument("--num-rounds", type=int, default=500)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    args = parser.parse_args()
    train(args)
