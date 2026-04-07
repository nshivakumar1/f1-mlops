"""Unit tests for OpenF1 client feature vector construction."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../lambda/enrichment"))

from openf1_client import build_feature_vector, DRIVER_GRID, ALL_DRIVER_NUMBERS

MOCK_SESSION_DATA = {
    "session_key": "9999",
    "stints": {
        1: [{"lap_start": 1, "lap_end": 12, "stint_number": 1, "compound": "MEDIUM"}],
    },
    "intervals": {
        1: [{"lap_number": 12, "gap_to_leader": "5.3", "interval": "1.2"}],
    },
    "laps": {
        1: [
            {"lap_number": 9,  "duration_sector_1": 28.1},
            {"lap_number": 10, "duration_sector_1": 28.3},
            {"lap_number": 11, "duration_sector_1": 28.2},
            {"lap_number": 12, "duration_sector_1": 29.5},
        ],
    },
    "weather": {"air_temperature": 28.5, "track_temperature": 44.2, "rainfall": False},
    "pit": {},
    "car_data": {},
}


def test_driver_grid_has_22_drivers():
    assert len(DRIVER_GRID) == 22


def test_all_driver_numbers_count():
    assert len(ALL_DRIVER_NUMBERS) == 22


def test_driver_grid_contains_norris():
    assert 1 in DRIVER_GRID
    assert DRIVER_GRID[1]["name"] == "Lando Norris"
    assert DRIVER_GRID[1]["team"] == "McLaren"


def test_driver_grid_contains_new_teams():
    assert 27 in DRIVER_GRID
    assert DRIVER_GRID[27]["team"] == "Audi"
    assert 11 in DRIVER_GRID
    assert DRIVER_GRID[11]["team"] == "Cadillac"


def test_build_feature_vector_returns_18_features():
    result = build_feature_vector(1, MOCK_SESSION_DATA)
    assert result is not None
    assert len(result["features"]) == 18
    assert len(result["feature_names"]) == 18


def test_feature_vector_values():
    result = build_feature_vector(1, MOCK_SESSION_DATA)
    f = result["features"]
    tyre_age, stint_number, gap_to_leader, air_temp, track_temp, rainfall, sector_delta, \
        tyre_age_sq, heat_deg, wet_stint, abs_sector_delta, \
        deg_rate, gap_trend, rolling_sector_delta_5, tyre_stress_index, \
        compound_soft, compound_medium, compound_hard = f

    assert tyre_age == 11           # lap_end(12) - lap_start(1)
    assert stint_number == 1
    assert abs(gap_to_leader - 5.3) < 0.01
    assert abs(air_temp - 28.5) < 0.01
    assert abs(track_temp - 44.2) < 0.01
    assert rainfall == 0
    assert sector_delta > 0         # lap 12 sector 1 slower than avg of laps 9-11
    assert tyre_age_sq == 121       # 11 ** 2
    assert abs(heat_deg - 44.2 * 11 / 100.0) < 0.01
    assert wet_stint == 0           # rainfall(0) * stint_number(1)
    assert abs_sector_delta == sector_delta  # positive delta
    # Rolling features — values depend on lap history, just verify they are numeric
    assert isinstance(deg_rate, (int, float))
    assert isinstance(gap_trend, (int, float))
    assert isinstance(rolling_sector_delta_5, (int, float))
    assert isinstance(tyre_stress_index, (int, float))
    # Compound one-hot — MEDIUM compound
    assert compound_soft == 0
    assert compound_medium == 1
    assert compound_hard == 0


def test_rainfall_flag():
    wet_data = {
        **MOCK_SESSION_DATA,
        "weather": {"air_temperature": 30, "track_temperature": 50, "rainfall": True},
        "stints": {44: [{"lap_start": 1, "lap_end": 5, "stint_number": 1, "compound": "INTERMEDIATE"}]},
        "intervals": {44: [{"gap_to_leader": None}]},
        "laps": {44: []},
        "pit": {},
        "car_data": {},
    }
    result = build_feature_vector(44, wet_data)
    assert result["features"][5] == 1  # rainfall flag


def test_build_feature_vector_returns_none_on_bad_session_data():
    result = build_feature_vector(1, {})  # missing keys → exception → None
    assert result is None


def test_feature_vector_metadata():
    result = build_feature_vector(1, MOCK_SESSION_DATA)
    assert result["driver_name"] == "Lando Norris"
    assert result["team"] == "McLaren"
    assert result["session_key"] == "9999"
    assert result["tyre_compound"] == "MEDIUM"
