"""
Lambda REST Handler — serves API Gateway requests
  POST /predict/pitstop    — on-demand pitstop prediction for a single driver
  GET  /predict/positions/{session_key} — cached race position predictions
"""
import json
import os
import boto3
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ["S3_BUCKET"]
SAGEMAKER_ENDPOINT = os.environ["SAGEMAKER_ENDPOINT"]
AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

s3 = boto3.client("s3", region_name=AWS_REGION)
sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def handle_pitstop_post(body: dict) -> dict:
    """
    POST /predict/pitstop
    Body: {"features": [tyre_age, stint_no, gap, air_temp, track_temp, rainfall, sector_delta]}
    """
    features = body.get("features")
    if not features or len(features) != 7:
        return _response(400, {
            "error": "features must be a list of exactly 7 values",
            "required": ["tyre_age", "stint_number", "gap_to_leader",
                         "air_temperature", "track_temperature", "rainfall", "sector_delta"]
        })

    # Apply feature engineering to match training features (11 total)
    tyre_age, stint_number, gap, air_temp, track_temp, rainfall, sector_delta = features
    engineered = features + [
        tyre_age ** 2,                        # tyre_age_sq
        track_temp * tyre_age / 100.0,        # heat_deg_interaction
        rainfall * stint_number,              # wet_stint
        abs(sector_delta),                    # abs_sector_delta
    ]
    payload = {"instances": [engineered]}
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=json.dumps(payload),
    )
    result = json.loads(response["Body"].read().decode())

    return _response(200, {
        "driver_number": body.get("driver_number"),
        "session_key": body.get("session_key"),
        "features": features,
        "prediction": result.get("predictions", [{}])[0],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def handle_positions_get(session_key: str) -> dict:
    """
    GET /predict/positions/{session_key}
    Returns latest cached inference results from S3.
    """
    prefix = f"logs/inference/session_{session_key}/"
    try:
        response = s3.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix,
        )
        objects = response.get("Contents", [])
        if not objects:
            return _response(404, {"error": f"No predictions found for session {session_key}"})

        # Get most recent file
        latest = sorted(objects, key=lambda x: x["LastModified"], reverse=True)[0]
        obj = s3.get_object(Bucket=S3_BUCKET, Key=latest["Key"])
        data = json.loads(obj["Body"].read().decode())

        return _response(200, {
            "session_key": session_key,
            "prediction_time": data.get("timestamp"),
            "safety_car_active": data.get("safety_car_active", False),
            "predictions": [
                {
                    "driver_number": p["driver_number"],
                    "driver_name": p["driver_name"],
                    "team": p["team"],
                    "tyre_compound": p.get("tyre_compound"),
                    "tyre_age": p["features"][0],
                    "pitstop_probability": p["prediction"].get("pitstop_probability", 0),
                    "confidence": p["prediction"].get("confidence", 0),
                }
                for p in sorted(
                    data.get("predictions", []),
                    key=lambda x: x["prediction"].get("pitstop_probability", 0),
                    reverse=True
                )
            ],
        })
    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        return _response(500, {"error": "Internal server error"})


def handle_sessions_list() -> dict:
    """GET /sessions — lists all available sessions from S3."""
    try:
        result = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix="logs/inference/", Delimiter="/")
        prefixes = result.get("CommonPrefixes", [])
        sessions = []
        for p in prefixes:
            parts = p["Prefix"].rstrip("/").split("_")
            if len(parts) >= 2:
                sessions.append(parts[-1])
        return _response(200, {"sessions": sorted(sessions, reverse=True)})
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        return _response(500, {"error": "Internal server error"})


def handle_latest_session() -> dict:
    """GET /sessions/latest — returns most recent session predictions."""
    try:
        result = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix="logs/inference/")
        objects = result.get("Contents", [])
        if not objects:
            return _response(404, {"error": "No predictions found yet"})
        latest = sorted(objects, key=lambda x: x["LastModified"], reverse=True)[0]
        parts = latest["Key"].split("/")
        session_part = next((p for p in parts if p.startswith("session_")), None)
        session_key = session_part.replace("session_", "") if session_part else "unknown"
        obj = s3.get_object(Bucket=S3_BUCKET, Key=latest["Key"])
        data = json.loads(obj["Body"].read().decode())
        return _response(200, {
            "session_key": session_key,
            "prediction_time": data.get("timestamp"),
            "safety_car_active": data.get("safety_car_active", False),
            "processing_time_ms": data.get("processing_time_ms"),
            "predictions": [
                {
                    "driver_number": p["driver_number"],
                    "driver_name": p["driver_name"],
                    "team": p["team"],
                    "tyre_compound": p.get("tyre_compound"),
                    "tyre_age": p["features"][0],
                    "pitstop_probability": p["prediction"].get("pitstop_probability", 0),
                    "confidence": p["prediction"].get("confidence", 0),
                }
                for p in sorted(
                    data.get("predictions", []),
                    key=lambda x: x["prediction"].get("pitstop_probability", 0),
                    reverse=True,
                )
            ],
        })
    except Exception as e:
        logger.error(f"Error fetching latest session: {e}")
        return _response(500, {"error": "Internal server error"})


def lambda_handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}

    logger.info(f"{method} {path}")

    if method == "POST" and "/predict/pitstop" in path:
        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return _response(400, {"error": "Invalid JSON body"})
        return handle_pitstop_post(body)

    elif method == "GET" and path.rstrip("/").endswith("/sessions/latest"):
        return handle_latest_session()

    elif method == "GET" and path.rstrip("/").endswith("/sessions"):
        return handle_sessions_list()

    elif method == "GET" and "/predict/positions/" in path:
        session_key = path_params.get("session_key") or path.split("/")[-1]
        return handle_positions_get(session_key)

    return _response(404, {"error": f"Route not found: {method} {path}"})
