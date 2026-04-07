"""
SageMaker Training Script — Pitstop Window Predictor
Ensemble: XGBoost + CatBoost + LightGBM → Logistic Regression meta-learner
Target: pitstop_within_3_laps (0 or 1)
Target metric: AUC >= 0.90 (up from XGBoost-only 0.82)

Feature set (18 features):
  7 raw:     tyre_age, stint_number, gap_to_leader, air_temperature,
             track_temperature, rainfall, sector_delta
  4 derived: tyre_age_sq, heat_deg_interaction, wet_stint, abs_sector_delta
  4 rolling: deg_rate (pace loss per lap), gap_trend (closing/opening),
             rolling_sector_delta_5 (5-lap avg), tyre_stress_index
  3 encoded: tyre_compound_soft, tyre_compound_medium, tyre_compound_hard
             (one-hot; INTER/WET map to their own flags via rainfall)
"""
import argparse
import os
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import roc_auc_score, classification_report, accuracy_score
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
import xgboost as xgb
import lightgbm as lgb
from catboost import CatBoostClassifier

# ── Feature columns ────────────────────────────────────────────────────────────
RAW_FEATURES = [
    "tyre_age",
    "stint_number",
    "gap_to_leader",
    "air_temperature",
    "track_temperature",
    "rainfall",
    "sector_delta",
]
DERIVED_FEATURES = [
    "tyre_age_sq",
    "heat_deg_interaction",
    "wet_stint",
    "abs_sector_delta",
]
ROLLING_FEATURES = [
    "deg_rate",
    "gap_trend",
    "rolling_sector_delta_5",
    "tyre_stress_index",
]
COMPOUND_FEATURES = [
    "compound_soft",
    "compound_medium",
    "compound_hard",
]
ALL_FEATURES = RAW_FEATURES + DERIVED_FEATURES + ROLLING_FEATURES + COMPOUND_FEATURES
TARGET_COL = "pitstop_within_3_laps"
AUC_THRESHOLD = 0.90


# ── Data loading ───────────────────────────────────────────────────────────────
def load_data(data_dir: str) -> pd.DataFrame:
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


# ── Feature engineering ────────────────────────────────────────────────────────
def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build all derived, rolling, and encoded features.
    Requires: session_key, driver_number, lap_number sorted before calling.
    """
    df = df.sort_values(["session_key", "driver_number", "lap_number"]).reset_index(drop=True)
    grp = df.groupby(["session_key", "driver_number"])

    # ── Derived (same as before) ──
    df["tyre_age_sq"] = df["tyre_age"] ** 2
    df["heat_deg_interaction"] = df["track_temperature"] * df["tyre_age"] / 100.0
    df["wet_stint"] = df["rainfall"] * df["stint_number"]
    df["abs_sector_delta"] = df["sector_delta"].abs()

    # ── Rolling features ──

    # deg_rate: lap-over-lap change in sector_delta (pace loss acceleration)
    # Positive = getting slower = tyres degrading
    df["deg_rate"] = grp["sector_delta"].diff(1).fillna(0)

    # gap_trend: change in gap_to_leader over last 3 laps
    # Negative = closing = undercut threat building
    df["gap_trend"] = grp["gap_to_leader"].diff(3).fillna(0)

    # rolling_sector_delta_5: 5-lap rolling mean of abs sector delta
    # Captures sustained pace loss, not just single-lap blips
    df["rolling_sector_delta_5"] = (
        grp["abs_sector_delta"]
        .transform(lambda x: x.rolling(5, min_periods=1).mean())
    )

    # tyre_stress_index: tyre_age × rolling_sector_delta_5 / 100
    # High when old tyres are also losing pace — key undercut signal
    df["tyre_stress_index"] = df["tyre_age"] * df["rolling_sector_delta_5"] / 100.0

    # ── Tyre compound one-hot encoding ──
    # tyre_compound column expected: SOFT, MEDIUM, HARD, INTERMEDIATE, WET
    compound = df.get("tyre_compound", pd.Series(["UNKNOWN"] * len(df)))
    compound_upper = compound.str.upper().fillna("UNKNOWN")
    df["compound_soft"] = (compound_upper == "SOFT").astype(int)
    df["compound_medium"] = (compound_upper == "MEDIUM").astype(int)
    df["compound_hard"] = (compound_upper == "HARD").astype(int)
    # INTERMEDIATE / WET captured by rainfall feature already

    return df


# ── Individual model trainers ──────────────────────────────────────────────────
def train_xgboost(X_train, y_train, X_val, y_val, scale_pos_weight, args):
    print("\n--- Training XGBoost ---")
    model = xgb.XGBClassifier(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        eval_metric="auc",
        random_state=42,
        tree_method="hist",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=50)
    auc = roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])
    print(f"XGBoost val AUC: {auc:.4f}")
    return model, auc


def train_lightgbm(X_train, y_train, X_val, y_val, scale_pos_weight, args, feature_names):
    print("\n--- Training LightGBM ---")
    train_set = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
    val_set = lgb.Dataset(X_val, label=y_val, reference=train_set, feature_name=feature_names)
    params = {
        "objective": "binary",
        "metric": "auc",
        "learning_rate": args.learning_rate,
        "num_leaves": 63,
        "max_depth": args.max_depth,
        "min_child_samples": 20,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "scale_pos_weight": scale_pos_weight,
        "random_state": 42,
        "verbosity": -1,
    }
    callbacks = [lgb.early_stopping(50, verbose=False), lgb.log_evaluation(50)]
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=args.n_estimators,
        valid_sets=[val_set],
        callbacks=callbacks,
    )
    proba = booster.predict(X_val)
    auc = roc_auc_score(y_val, proba)
    print(f"LightGBM val AUC: {auc:.4f}")
    return booster, auc


def train_catboost(X_train, y_train, X_val, y_val, scale_pos_weight, args):
    print("\n--- Training CatBoost ---")
    model = CatBoostClassifier(
        iterations=args.n_estimators,
        depth=args.max_depth,
        learning_rate=args.learning_rate,
        scale_pos_weight=scale_pos_weight,
        eval_metric="AUC",
        random_seed=42,
        verbose=50,
        early_stopping_rounds=50,
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val))
    auc = roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])
    print(f"CatBoost val AUC: {auc:.4f}")
    return model, auc


# ── Stacking ensemble ──────────────────────────────────────────────────────────
def build_stacking_meta_features(
    xgb_model, lgb_model, cat_model, X, is_lgb_booster=True
):
    """Return [n_samples, 3] array of base model probabilities."""
    xgb_proba = xgb_model.predict_proba(X)[:, 1]
    lgb_proba = lgb_model.predict(X) if is_lgb_booster else lgb_model.predict_proba(X)[:, 1]
    cat_proba = cat_model.predict_proba(X)[:, 1]
    return np.column_stack([xgb_proba, lgb_proba, cat_proba])


def train_meta_learner(meta_X_train, y_train, meta_X_val, y_val):
    print("\n--- Training Logistic Regression meta-learner ---")
    scaler = StandardScaler()
    meta_X_train_scaled = scaler.fit_transform(meta_X_train)
    meta_X_val_scaled = scaler.transform(meta_X_val)

    meta = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    meta.fit(meta_X_train_scaled, y_train)

    meta_proba = meta.predict_proba(meta_X_val_scaled)[:, 1]
    meta_pred = (meta_proba >= 0.5).astype(int)
    auc = roc_auc_score(y_val, meta_proba)
    acc = accuracy_score(y_val, meta_pred)
    print(f"Ensemble val AUC: {auc:.4f} | Accuracy: {acc:.4f}")
    print(f"Meta-learner weights (XGB, LGB, CAT): {meta.coef_[0].round(4)}")
    print(classification_report(y_val, meta_pred))
    return meta, scaler, auc, acc


# ── Main training entry point ──────────────────────────────────────────────────
def train(args):
    print("=== F1 Pitstop Predictor — Stacking Ensemble Training ===")
    print(f"Models: XGBoost + LightGBM + CatBoost → Logistic Regression")

    df = load_data(args.data_dir)
    df = engineer_features(df)

    missing = [c for c in ALL_FEATURES + [TARGET_COL] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    X = df[ALL_FEATURES].fillna(0).values
    y = df[TARGET_COL].values

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    print(f"Train: {len(X_train)} | Val: {len(X_val)} | Positive rate: {y.mean():.3f}")

    scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    print(f"Scale pos weight: {scale_pos_weight:.1f}")

    # Train base models
    xgb_model, xgb_auc = train_xgboost(X_train, y_train, X_val, y_val, scale_pos_weight, args)
    lgb_model, lgb_auc = train_lightgbm(X_train, y_train, X_val, y_val, scale_pos_weight, args, ALL_FEATURES)
    cat_model, cat_auc = train_catboost(X_train, y_train, X_val, y_val, scale_pos_weight, args)

    # Build meta features from base model predictions
    meta_X_train = build_stacking_meta_features(xgb_model, lgb_model, cat_model, X_train)
    meta_X_val = build_stacking_meta_features(xgb_model, lgb_model, cat_model, X_val)

    # Train meta-learner
    meta_model, meta_scaler, ensemble_auc, ensemble_acc = train_meta_learner(
        meta_X_train, y_train, meta_X_val, y_val
    )

    # Print comparison
    print("\n=== Model Comparison ===")
    print(f"  XGBoost AUC:  {xgb_auc:.4f}")
    print(f"  LightGBM AUC: {lgb_auc:.4f}")
    print(f"  CatBoost AUC: {cat_auc:.4f}")
    print(f"  Ensemble AUC: {ensemble_auc:.4f}  ← deployed")
    print(f"  Ensemble Acc: {ensemble_acc:.4f}")

    # Metrics for SageMaker Pipeline ConditionStep
    metrics = {
        "auc": ensemble_auc,
        "accuracy": ensemble_acc,
        "auc_threshold": AUC_THRESHOLD,
        "approved": ensemble_auc >= AUC_THRESHOLD,
        "xgb_auc": xgb_auc,
        "lgb_auc": lgb_auc,
        "cat_auc": cat_auc,
        "n_train": len(X_train),
        "n_val": len(X_val),
        "positive_rate": float(y.mean()),
        "n_features": len(ALL_FEATURES),
    }
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "evaluation.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    if ensemble_auc < AUC_THRESHOLD:
        print(f"WARNING: AUC {ensemble_auc:.4f} below threshold {AUC_THRESHOLD}.")

    # Save all models + scaler + feature list
    model_dir = os.environ.get("SM_MODEL_DIR", args.model_dir)
    os.makedirs(model_dir, exist_ok=True)

    xgb_model.save_model(os.path.join(model_dir, "xgboost_pitstop.json"))
    lgb_model.save_model(os.path.join(model_dir, "lightgbm_pitstop.txt"))
    joblib.dump(cat_model, os.path.join(model_dir, "catboost_pitstop.pkl"))
    joblib.dump(meta_model, os.path.join(model_dir, "meta_learner.pkl"))
    joblib.dump(meta_scaler, os.path.join(model_dir, "meta_scaler.pkl"))

    with open(os.path.join(model_dir, "feature_names.json"), "w") as f:
        json.dump(ALL_FEATURES, f, indent=2)

    with open(os.path.join(model_dir, "model_info.json"), "w") as f:
        json.dump({
            "model_type": "stacking_ensemble",
            "base_models": ["xgboost", "lightgbm", "catboost"],
            "meta_learner": "logistic_regression",
            "n_features": len(ALL_FEATURES),
            "feature_names": ALL_FEATURES,
            "auc": ensemble_auc,
            "accuracy": ensemble_acc,
        }, f, indent=2)

    print(f"\nAll models saved to {model_dir}")
    return ensemble_auc


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default=os.environ.get("SM_CHANNEL_TRAINING", "/opt/ml/input/data/training"))
    parser.add_argument("--model-dir", type=str, default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    parser.add_argument("--output-dir", type=str, default=os.environ.get("SM_OUTPUT_DATA_DIR", "/opt/ml/output/data"))
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    args = parser.parse_args()
    train(args)
