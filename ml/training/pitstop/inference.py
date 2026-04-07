"""
SageMaker Inference Script — Pitstop Stacking Ensemble
Loads XGBoost + LightGBM + CatBoost base models and Logistic Regression meta-learner.
Packaged at code/inference.py inside model.tar.gz (SageMaker script mode).

Expected feature order (18 features):
  tyre_age, stint_number, gap_to_leader, air_temperature, track_temperature,
  rainfall, sector_delta, tyre_age_sq, heat_deg_interaction, wet_stint,
  abs_sector_delta, deg_rate, gap_trend, rolling_sector_delta_5,
  tyre_stress_index, compound_soft, compound_medium, compound_hard
"""
import json
import os
import numpy as np
import joblib
import xgboost as xgb
import lightgbm as lgb

_xgb_model = None
_lgb_model = None
_cat_model = None
_meta_model = None
_meta_scaler = None
_feature_names = None


def model_fn(model_dir: str):
    """Load all ensemble components from model_dir."""
    global _xgb_model, _lgb_model, _cat_model, _meta_model, _meta_scaler, _feature_names

    # XGBoost
    xgb_path = os.path.join(model_dir, "xgboost_pitstop.json")
    _xgb_model = xgb.XGBClassifier()
    _xgb_model.load_model(xgb_path)

    # LightGBM
    lgb_path = os.path.join(model_dir, "lightgbm_pitstop.txt")
    _lgb_model = lgb.Booster(model_file=lgb_path)

    # CatBoost
    cat_path = os.path.join(model_dir, "catboost_pitstop.pkl")
    _cat_model = joblib.load(cat_path)

    # Meta-learner + scaler
    _meta_model = joblib.load(os.path.join(model_dir, "meta_learner.pkl"))
    _meta_scaler = joblib.load(os.path.join(model_dir, "meta_scaler.pkl"))

    # Feature names
    fn_path = os.path.join(model_dir, "feature_names.json")
    with open(fn_path) as f:
        _feature_names = json.load(f)

    print(f"Ensemble loaded: {len(_feature_names)} features")
    return {
        "xgb": _xgb_model,
        "lgb": _lgb_model,
        "cat": _cat_model,
        "meta": _meta_model,
        "scaler": _meta_scaler,
    }


def input_fn(request_body: str, content_type: str = "application/json"):
    """Parse incoming request."""
    data = json.loads(request_body)
    instances = data.get("instances", [data.get("features", [])])
    return np.array(instances, dtype=float)


def predict_fn(input_data, models):
    """Run stacking ensemble inference."""
    xgb_proba = models["xgb"].predict_proba(input_data)[:, 1]
    lgb_proba = models["lgb"].predict(input_data)
    cat_proba = models["cat"].predict_proba(input_data)[:, 1]

    meta_X = np.column_stack([xgb_proba, lgb_proba, cat_proba])
    meta_X_scaled = models["scaler"].transform(meta_X)
    ensemble_proba = models["meta"].predict_proba(meta_X_scaled)[:, 1]

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
                "catboost": round(float(cat_proba[i]), 4),
            },
        })
    return predictions


def output_fn(predictions, accept: str = "application/json"):
    return json.dumps({"predictions": predictions}), "application/json"
