"""
SageMaker Inference Script — Final Position Predictor (Random Forest)
SageMaker sklearn containers call these four functions automatically.
"""
import os
import json
import joblib
import numpy as np

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


def model_fn(model_dir):
    return joblib.load(os.path.join(model_dir, "rf_position.pkl"))


def input_fn(request_body, request_content_type):
    # Accepts JSON: {"instances": [[f1, f2, ...], ...]}
    data = json.loads(request_body)
    return np.array(data["instances"])


def predict_fn(input_data, model):
    return model.predict(input_data)


def output_fn(prediction, response_content_type):
    # Returns JSON: {"predictions": [{"predicted_position": X, "win_probability": Y}, ...]}
    positions = prediction.tolist()
    # Convert predicted positions to win probabilities.
    # Lower predicted position = higher win chance.
    # win_prob = softmax of (23 - predicted_pos) so P1 pred = highest prob.
    scores = [max(0.1, 23.0 - p) for p in positions]
    total = sum(scores)
    results = [
        {
            "predicted_position": round(float(pos), 1),
            "win_probability": round(score / total, 4),
        }
        for pos, score in zip(positions, scores)
    ]
    return json.dumps({"predictions": results})
