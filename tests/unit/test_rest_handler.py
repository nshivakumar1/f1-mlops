"""Unit tests for REST handler Lambda."""
import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../lambda/rest_handler"))

# Mock boto3 before import
import unittest.mock
mock_boto3 = unittest.mock.MagicMock()
sys.modules['boto3'] = mock_boto3

os.environ["S3_BUCKET"] = "test-bucket"
os.environ["SAGEMAKER_ENDPOINT"] = "f1-mlops-pitstop-endpoint"
os.environ["AWS_REGION_NAME"] = "us-east-1"

from handler import lambda_handler, _response, handle_pitstop_post


def make_event(method: str, path: str, body: dict = None, path_params: dict = None) -> dict:
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body else None,
        "pathParameters": path_params or {},
    }


def test_response_format():
    resp = _response(200, {"key": "value"})
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"key": "value"}
    assert resp["headers"]["Content-Type"] == "application/json"


def test_pitstop_post_missing_features():
    event = make_event("POST", "/v1/predict/pitstop", {"driver_number": 1})
    result = lambda_handler(event, {})
    assert result["statusCode"] == 400
    body = json.loads(result["body"])
    assert "error" in body


def test_pitstop_post_wrong_feature_count():
    event = make_event("POST", "/v1/predict/pitstop", {
        "features": [1, 2, 3],  # Only 3, need 7
        "driver_number": 1
    })
    result = lambda_handler(event, {})
    assert result["statusCode"] == 400


def test_unknown_route():
    event = make_event("GET", "/v1/unknown")
    result = lambda_handler(event, {})
    assert result["statusCode"] == 404


def test_invalid_json_body():
    event = {
        "httpMethod": "POST",
        "path": "/v1/predict/pitstop",
        "body": "not-valid-json",
        "pathParameters": {},
    }
    result = lambda_handler(event, {})
    assert result["statusCode"] == 400
