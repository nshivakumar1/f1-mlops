"""
Lambda REST Handler — serves API Gateway requests
  POST /predict/pitstop    — on-demand pitstop prediction for a single driver
  GET  /predict/positions/{session_key} — cached race position predictions
  GET  /positions/latest   — live driver positions proxied from OpenF1
  GET  /track/{circuit_key} — static circuit track layout from Multiviewer
"""
import json
import os
import boto3
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ["S3_BUCKET"]
SAGEMAKER_ENDPOINT = os.environ["SAGEMAKER_ENDPOINT"]
AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

s3 = boto3.client("s3", region_name=AWS_REGION)
sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)

# OpenF1 country_name → Multiviewer circuit key (2026 F1 calendar + common circuits)
COUNTRY_TO_CIRCUIT_KEY: dict = {
    "Australia":      "10",   # Melbourne
    "Japan":          "46",   # Suzuka
    "China":          "49",   # Shanghai
    "Bahrain":        "63",   # Sakhir
    "Saudi Arabia":   "149",  # Jeddah
    "United States":  "9",    # Austin (COTA) — Miami=151, Las Vegas=152
    "Miami":          "151",  # Miami
    "Las Vegas":      "152",  # Las Vegas
    "Monaco":         "22",   # Monte Carlo
    "Spain":          "15",   # Catalunya
    "Canada":         "23",   # Montreal
    "Austria":        "19",   # Spielberg (Red Bull Ring)
    "Great Britain":  "2",    # Silverstone
    "Hungary":        "4",    # Hungaroring
    "Belgium":        "7",    # Spa-Francorchamps
    "Netherlands":    "55",   # Zandvoort
    "Italy":          "39",   # Monza (Imola=6)
    "Azerbaijan":     "144",  # Baku
    "Singapore":      "61",   # Marina Bay
    "Mexico":         "65",   # Mexico City
    "Brazil":         "14",   # Interlagos
    "Qatar":          "150",  # Lusail
    "United Arab Emirates": "70",  # Yas Marina
}


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
            "commentary": data.get("commentary", ""),
            "predictions": [
                {
                    "driver_number": p["driver_number"],
                    "driver_name": p["driver_name"],
                    "team": p["team"],
                    "tyre_compound": p.get("tyre_compound"),
                    "tyre_age": p["features"][0],
                    "pitstop_probability": p["prediction"].get("pitstop_probability", 0),
                    "confidence": p["prediction"].get("confidence", 0),
                    "win_probability": p.get("win_probability", 0.0),
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
            if len(parts) >= 2 and parts[-1].isdigit():
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
        country_name = data.get("country_name", "")
        circuit_key = COUNTRY_TO_CIRCUIT_KEY.get(country_name, "")
        return _response(200, {
            "session_key": session_key,
            "country_name": country_name,
            "circuit_key": circuit_key,
            "prediction_time": data.get("timestamp"),
            "safety_car_active": data.get("safety_car_active", False),
            "processing_time_ms": data.get("processing_time_ms"),
            "commentary": data.get("commentary", ""),
            "predictions": [
                {
                    "driver_number": p["driver_number"],
                    "driver_name": p["driver_name"],
                    "team": p["team"],
                    "tyre_compound": p.get("tyre_compound"),
                    "tyre_age": p["features"][0],
                    "pitstop_probability": p["prediction"].get("pitstop_probability", 0),
                    "confidence": p["prediction"].get("confidence", 0),
                    "win_probability": p.get("win_probability", 0.0),
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


def handle_live_positions() -> dict:
    """GET /positions/latest — proxy OpenF1 live positions server-side."""
    try:
        # Get current session key from latest S3 prediction
        result = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix="logs/inference/")
        objects = result.get("Contents", [])
        session_key = "latest"
        if objects:
            latest_obj = sorted(objects, key=lambda x: x["LastModified"], reverse=True)[0]
            parts = latest_obj["Key"].split("/")
            session_part = next((p for p in parts if p.startswith("session_")), None)
            if session_part:
                key = session_part.replace("session_", "")
                if key.isdigit():
                    session_key = key

        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        url = f"https://api.openf1.org/v1/position?session_key={session_key}&date>={since}"
        req = urllib.request.Request(url, headers={"User-Agent": "f1-mlops/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        if not isinstance(data, list):
            return _response(200, {"session_key": session_key, "positions": []})

        # Keep only the latest position per driver
        latest = {}
        for p in data:
            num = p.get("driver_number")
            if num and (num not in latest or p.get("date", "") > latest[num].get("date", "")):
                latest[num] = {"driver_number": num, "x": p.get("x", 0), "y": p.get("y", 0), "date": p.get("date", "")}

        return _response(200, {"session_key": session_key, "positions": list(latest.values())})
    except urllib.error.HTTPError as e:
        logger.warning(f"OpenF1 positions HTTP {e.code}")
        return _response(200, {"session_key": session_key if "session_key" in dir() else "unknown", "positions": []})
    except Exception as e:
        logger.error(f"Error fetching live positions: {e}")
        return _response(200, {"positions": []})


def handle_track_layout(circuit_key: str) -> dict:
    """GET /track/{circuit_key} — proxy Multiviewer static circuit outline."""
    try:
        # Default to Melbourne (Australian GP) if no key provided
        key = circuit_key if circuit_key and circuit_key.isdigit() else "10"
        # Try years in reverse order to find available data
        for year in [2026, 2025, 2024, 2023, 2022, 2019]:
            url = f"https://api.multiviewer.app/api/v1/circuits/{key}/{year}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "f1-mlops/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                if data.get("x"):
                    return _response(200, {
                        "circuit_key": key,
                        "circuit_name": data.get("circuitName", ""),
                        "year": year,
                        "rotation": data.get("rotation", 0),
                        "x": data["x"],
                        "y": data["y"],
                    })
            except Exception:
                continue
        return _response(404, {"error": f"No track layout found for circuit {key}"})
    except Exception as e:
        logger.error(f"Error fetching track layout: {e}")
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

    elif method == "GET" and "/positions/latest" in path:
        return handle_live_positions()

    elif method == "GET" and "/track/" in path:
        circuit_key = path_params.get("circuit_key") or path.split("/")[-1]
        return handle_track_layout(circuit_key)

    return _response(404, {"error": f"Route not found: {method} {path}"})
