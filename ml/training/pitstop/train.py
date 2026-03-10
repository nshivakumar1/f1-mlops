"""
SageMaker Training Script — Pitstop Window Predictor
Algorithm: XGBoost 1.7 (binary classification)
Target: pitstop_within_3_laps (0 or 1)
Target metric: AUC >= 0.82
Features: tyre_age, stint_number, gap_to_leader, air_temp, track_temp, rainfall, sector_delta
"""
import argparse
import os
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, classification_report
from sklearn.preprocessing import StandardScaler
import xgboost as xgb

FEATURE_COLS = [
    "tyre_age",
    "stint_number",
    "gap_to_leader",
    "air_temperature",
    "track_temperature",
    "rainfall",
    "sector_delta",
]
TARGET_COL = "pitstop_within_3_laps"
AUC_THRESHOLD = 0.82


def load_data(data_dir: str) -> pd.DataFrame:
    """Load all Parquet files from the SageMaker input data channel."""
    dfs = []
    for fname in os.listdir(data_dir):
        if fname.endswith(".parquet"):
            dfs.append(pd.read_parquet(os.path.join(data_dir, fname)))
        elif fname.endswith(".csv"):
            dfs.append(pd.read_csv(os.path.join(data_dir, fname)))
    if not dfs:
        raise ValueError(f"No data files found in {data_dir}")
    df = pd.concat(dfs, ignore_index=True)
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns")
    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Additional feature engineering on top of Glue ETL output."""
    # Tyre age squared — captures accelerating degradation
    df["tyre_age_sq"] = df["tyre_age"] ** 2

    # High track temp × tyre age interaction
    df["heat_deg_interaction"] = df["track_temperature"] * df["tyre_age"] / 100.0

    # Rainfall × stint number (wet races have different pitstop cadence)
    df["wet_stint"] = df["rainfall"] * df["stint_number"]

    # Absolute sector delta
    df["abs_sector_delta"] = df["sector_delta"].abs()

    return df


def train(args):
    print("=== F1 Pitstop Predictor — XGBoost Training ===")

    # Load data
    data_dir = args.data_dir
    df = load_data(data_dir)
    df = engineer_features(df)

    # Validate columns
    extended_features = FEATURE_COLS + ["tyre_age_sq", "heat_deg_interaction", "wet_stint", "abs_sector_delta"]
    missing = [c for c in extended_features + [TARGET_COL] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    X = df[extended_features].fillna(0).values
    y = df[TARGET_COL].values

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
    print(f"Train: {len(X_train)} | Val: {len(X_val)} | Positive rate: {y.mean():.3f}")

    # Class imbalance — pitstops are ~5% of laps
    scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)

    model = xgb.XGBClassifier(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        use_label_encoder=False,
        eval_metric="auc",
        random_state=42,
        tree_method="hist",
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=50,
    )

    y_pred_proba = model.predict_proba(X_val)[:, 1]
    auc = roc_auc_score(y_val, y_pred_proba)
    y_pred = (y_pred_proba >= 0.5).astype(int)

    print(f"\n=== Validation Results ===")
    print(f"AUC: {auc:.4f} (threshold: {AUC_THRESHOLD})")
    print(classification_report(y_val, y_pred))

    # Feature importance
    feature_importance = dict(zip(extended_features, model.feature_importances_))
    print(f"\nFeature Importance: {json.dumps({k: round(float(v), 4) for k, v in sorted(feature_importance.items(), key=lambda x: -x[1])}, indent=2)}")

    # Write metrics for SageMaker Pipeline ConditionStep
    metrics = {
        "auc": auc,
        "auc_threshold": AUC_THRESHOLD,
        "approved": auc >= AUC_THRESHOLD,
        "n_train": len(X_train),
        "n_val": len(X_val),
        "positive_rate": float(y.mean()),
    }
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "evaluation.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    if auc < AUC_THRESHOLD:
        print(f"WARNING: AUC {auc:.4f} below threshold {AUC_THRESHOLD}. Model will not be registered.")

    # Save model
    model_dir = os.environ.get("SM_MODEL_DIR", args.model_dir)
    os.makedirs(model_dir, exist_ok=True)
    joblib.dump(model, os.path.join(model_dir, "xgboost_pitstop.pkl"))

    # Save feature list for inference
    with open(os.path.join(model_dir, "feature_names.json"), "w") as f:
        json.dump(extended_features, f)

    print(f"Model saved to {model_dir}")
    return auc


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default=os.environ.get("SM_CHANNEL_TRAINING", "/opt/ml/input/data/training"))
    parser.add_argument("--model-dir", type=str, default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    parser.add_argument("--output-dir", type=str, default=os.environ.get("SM_OUTPUT_DATA_DIR", "/opt/ml/output/data"))
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    args = parser.parse_args()
    train(args)
