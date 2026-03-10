"""
SageMaker Inference Script — Pitstop Model
Handles model loading and prediction for the serverless endpoint.
"""
import json
import os
import joblib
import numpy as np

MODEL_PATH = os.path.join(os.environ.get("SM_MODEL_DIR", "/opt/ml/model"), "xgboost_pitstop.pkl")
_model = None


def model_fn(model_dir: str):
    global _model
    _model = joblib.load(os.path.join(model_dir, "xgboost_pitstop.pkl"))
    return _model


def input_fn(request_body: str, content_type: str = "application/json"):
    data = json.loads(request_body)
    instances = data.get("instances", [data.get("features", [])])
    return np.array(instances, dtype=float)


def predict_fn(input_data, model):
    proba = model.predict_proba(input_data)[:, 1]
    predictions = []
    for p in proba:
        # Confidence: how far from 0.5 the prediction is (certainty measure)
        confidence = abs(p - 0.5) * 2
        predictions.append({
            "pitstop_probability": round(float(p), 4),
            "confidence": round(float(confidence), 4),
            "recommendation": "PIT" if p > 0.70 else "STAY",
        })
    return predictions


def output_fn(predictions, accept: str = "application/json"):
    return json.dumps({"predictions": predictions}), "application/json"
