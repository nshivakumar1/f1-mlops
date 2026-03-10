"""Unit tests for OpenF1 client feature vector construction."""
import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../lambda/enrichment"))

from openf1_client import build_feature_vector, DRIVER_GRID, ALL_DRIVER_NUMBERS


MOCK_STINTS = [{"lap_start": 1, "lap_end": 12, "stint_number": 1, "compound": "MEDIUM"}]
MOCK_INTERVALS = [{"lap_number": 12, "gap_to_leader": "5.3", "interval": "1.2"}]
MOCK_WEATHER = {"air_temperature": 28.5, "track_temperature": 44.2, "rainfall": False}
MOCK_LAPS = [
    {"lap_number": 9,  "duration_sector_1": 28.1},
    {"lap_number": 10, "duration_sector_1": 28.3},
    {"lap_number": 11, "duration_sector_1": 28.2},
    {"lap_number": 12, "duration_sector_1": 29.5},
]


def test_driver_grid_has_22_drivers():
    assert len(DRIVER_GRID) == 22


def test_all_driver_numbers_count():
    assert len(ALL_DRIVER_NUMBERS) == 22


def test_driver_grid_contains_norris():
    assert 1 in DRIVER_GRID
    assert DRIVER_GRID[1]["name"] == "Lando Norris"
    assert DRIVER_GRID[1]["team"] == "McLaren"


def test_driver_grid_contains_new_teams():
    # Audi
    assert 27 in DRIVER_GRID
    assert DRIVER_GRID[27]["team"] == "Audi"
    # Cadillac
    assert 11 in DRIVER_GRID
    assert DRIVER_GRID[11]["team"] == "Cadillac"


@patch("openf1_client.get_stints", return_value=MOCK_STINTS)
@patch("openf1_client.get_intervals", return_value=MOCK_INTERVALS)
@patch("openf1_client.get_weather", return_value=MOCK_WEATHER)
@patch("openf1_client.get_laps", return_value=MOCK_LAPS)
def test_build_feature_vector_returns_7_features(mock_laps, mock_weather, mock_intervals, mock_stints):
    result = build_feature_vector("9999", 1)
    assert result is not None
    assert len(result["features"]) == 7
    assert len(result["feature_names"]) == 7


@patch("openf1_client.get_stints", return_value=MOCK_STINTS)
@patch("openf1_client.get_intervals", return_value=MOCK_INTERVALS)
@patch("openf1_client.get_weather", return_value=MOCK_WEATHER)
@patch("openf1_client.get_laps", return_value=MOCK_LAPS)
def test_feature_vector_values(mock_laps, mock_weather, mock_intervals, mock_stints):
    result = build_feature_vector("9999", 1)
    features = result["features"]

    tyre_age, stint_number, gap_to_leader, air_temp, track_temp, rainfall, sector_delta = features

    assert tyre_age == 11  # lap_end - lap_start = 12 - 1
    assert stint_number == 1
    assert abs(gap_to_leader - 5.3) < 0.01
    assert abs(air_temp - 28.5) < 0.01
    assert abs(track_temp - 44.2) < 0.01
    assert rainfall == 0  # not raining
    assert sector_delta > 0  # sector 1 slower than average


@patch("openf1_client.get_stints", return_value=[{"lap_start": 1, "lap_end": 5, "stint_number": 1, "compound": "SOFT"}])
@patch("openf1_client.get_intervals", return_value=[{"lap_number": 5, "gap_to_leader": None}])
@patch("openf1_client.get_weather", return_value={"air_temperature": 30, "track_temperature": 50, "rainfall": True})
@patch("openf1_client.get_laps", return_value=[])
def test_rainfall_flag(mock_laps, mock_weather, mock_intervals, mock_stints):
    result = build_feature_vector("9999", 44)
    assert result["features"][5] == 1  # rainfall = 1


@patch("openf1_client.get_stints", side_effect=Exception("API timeout"))
def test_build_feature_vector_returns_none_on_error(mock_stints):
    result = build_feature_vector("9999", 1)
    assert result is None


@patch("openf1_client.get_stints", return_value=MOCK_STINTS)
@patch("openf1_client.get_intervals", return_value=MOCK_INTERVALS)
@patch("openf1_client.get_weather", return_value=MOCK_WEATHER)
@patch("openf1_client.get_laps", return_value=MOCK_LAPS)
def test_feature_vector_metadata(mock_laps, mock_weather, mock_intervals, mock_stints):
    result = build_feature_vector("9999", 1)
    assert result["driver_name"] == "Lando Norris"
    assert result["team"] == "McLaren"
    assert result["session_key"] == "9999"
    assert result["tyre_compound"] == "MEDIUM"
