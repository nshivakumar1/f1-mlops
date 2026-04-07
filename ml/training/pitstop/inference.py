"""
SageMaker Inference Script — Pitstop Stacking Ensemble
Loads XGBoost + LightGBM base models and Logistic Regression meta-learner.
Packaged at code/inference.py inside model.tar.gz (SageMaker script mode).

Container: sagemaker-xgboost:1.7-1 (XGBoost + sklearn + scipy pre-installed)
LightGBM bundled at /opt/ml/model/packages (manylinux cp39, --no-deps)

Expected feature order (18 features):
  tyre_age, stint_number, gap_to_leader, air_temperature, track_temperature,
  rainfall, sector_delta, tyre_age_sq, heat_deg_interaction, wet_stint,
  abs_sector_delta, deg_rate, gap_trend, rolling_sector_delta_5,
  tyre_stress_index, compound_soft, compound_medium, compound_hard
"""
import sys
import os

# Prepend bundled packages dir before any other imports
_pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packages")
if os.path.isdir(_pkg_dir):
    sys.path.insert(0, os.path.normpath(_pkg_dir))
# Also try the model_dir-relative path (SageMaker extracts to /opt/ml/model)
_pkg_dir2 = "/opt/ml/model/packages"
if os.path.isdir(_pkg_dir2):
    sys.path.insert(0, _pkg_dir2)

import json
import numpy as np
import xgboost as xgb
import lightgbm as lgb

_xgb_model = None
_lgb_model = None
_meta_coef = None       # shape [1, 2]
_meta_intercept = None  # shape [1]
_scaler_mean = None     # shape [2]
_scaler_scale = None    # shape [2]
_feature_names = None


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def model_fn(model_dir: str):
    """Load all ensemble components from model_dir.
    meta_learner.json and meta_scaler.json are used instead of joblib pkl
    to avoid numpy version incompatibility between training env and container.
    """
    global _xgb_model, _lgb_model, _meta_coef, _meta_intercept
    global _scaler_mean, _scaler_scale, _feature_names

    _xgb_model = xgb.XGBClassifier()
    _xgb_model.load_model(os.path.join(model_dir, "xgboost_pitstop.json"))

    _lgb_model = lgb.Booster(model_file=os.path.join(model_dir, "lightgbm_pitstop.txt"))

    with open(os.path.join(model_dir, "meta_learner.json")) as f:
        meta = json.load(f)
    _meta_coef = np.array(meta["coef"])          # [[w0, w1]]
    _meta_intercept = np.array(meta["intercept"]) # [b]

    with open(os.path.join(model_dir, "meta_scaler.json")) as f:
        scaler = json.load(f)
    _scaler_mean = np.array(scaler["mean"])
    _scaler_scale = np.array(scaler["scale"])

    with open(os.path.join(model_dir, "feature_names.json")) as f:
        _feature_names = json.load(f)

    print(f"XGB+LGB stacking ensemble loaded: {len(_feature_names)} features")
    return {
        "xgb": _xgb_model,
        "lgb": _lgb_model,
        "meta_coef": _meta_coef,
        "meta_intercept": _meta_intercept,
        "scaler_mean": _scaler_mean,
        "scaler_scale": _scaler_scale,
    }


def input_fn(request_body: str, content_type: str = "application/json"):
    data = json.loads(request_body)
    instances = data.get("instances", [data.get("features", [])])
    return np.array(instances, dtype=float)


def predict_fn(input_data, models):
    xgb_proba = models["xgb"].predict_proba(input_data)[:, 1]
    lgb_proba = models["lgb"].predict(input_data)

    # Manual StandardScaler + LogisticRegression (no sklearn/pickle dependency)
    meta_X = np.column_stack([xgb_proba, lgb_proba])
    meta_X_scaled = (meta_X - models["scaler_mean"]) / models["scaler_scale"]
    logits = meta_X_scaled @ models["meta_coef"].T + models["meta_intercept"]
    ensemble_proba = _sigmoid(logits[:, 0])

    predictions = []
    for i, p in enumerate(ensemble_proba):
        confidence = abs(p - 0.5) * 2
        predictions.append({
            "pitstop_probability": round(float(p), 4),
            "confidence": round(float(confidence), 4),
            "recommendation": "PIT" if p > 0.70 else "STAY",
            "base_models": {
                "xgboost": round(float(xgb_proba[i]), 4),
                "lightgbm": round(float(lgb_proba[i]), 4),
            },
        })
    return predictions


def output_fn(predictions, accept: str = "application/json"):
    return json.dumps({"predictions": predictions}), "application/json"
