"""
SageMaker Inference Script — Pitstop Model
Handles model loading and prediction for the serverless endpoint.
Packaged at code/inference.py inside model.tar.gz (SageMaker script mode).
"""
import json
import os
import numpy as np
import xgboost as xgb

_model = None


def model_fn(model_dir: str):
    """Load model from model_dir (SageMaker sets this to /opt/ml/model).
    Uses XGBoost native JSON format to avoid numpy version incompatibility.
    """
    global _model
    model_path = os.path.join(model_dir, "xgboost_pitstop.json")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model not found at {model_path}. Contents: {os.listdir(model_dir)}")
    _model = xgb.XGBClassifier()
    _model.load_model(model_path)
    return _model


def input_fn(request_body: str, content_type: str = "application/json"):
    """Parse incoming request body."""
    data = json.loads(request_body)
    instances = data.get("instances", [data.get("features", [])])
    return np.array(instances, dtype=float)


def predict_fn(input_data, model):
    """Run inference and return structured predictions."""
    proba = model.predict_proba(input_data)[:, 1]
    predictions = []
    for p in proba:
        confidence = abs(p - 0.5) * 2
        predictions.append({
            "pitstop_probability": round(float(p), 4),
            "confidence": round(float(confidence), 4),
            "recommendation": "PIT" if p > 0.70 else "STAY",
        })
    return predictions


def output_fn(predictions, accept: str = "application/json"):
    """Serialize predictions to JSON response."""
    return json.dumps({"predictions": predictions}), "application/json"
