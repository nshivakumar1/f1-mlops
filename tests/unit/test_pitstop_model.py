"""Unit tests for pitstop ML model training utilities."""
import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../ml/training/pitstop"))

from train import engineer_features, FEATURE_COLS, TARGET_COL, AUC_THRESHOLD


def make_sample_df(n: int = 100) -> pd.DataFrame:
    np.random.seed(42)
    df = pd.DataFrame({
        "tyre_age": np.random.randint(0, 40, n),
        "stint_number": np.random.randint(1, 4, n),
        "gap_to_leader": np.random.uniform(0, 60, n),
        "air_temperature": np.random.uniform(20, 40, n),
        "track_temperature": np.random.uniform(30, 60, n),
        "rainfall": np.random.randint(0, 2, n),
        "sector_delta": np.random.uniform(-2, 2, n),
        "pitstop_within_3_laps": np.random.randint(0, 2, n),
    })
    return df


def test_engineer_features_adds_columns():
    df = make_sample_df(50)
    result = engineer_features(df)
    assert "tyre_age_sq" in result.columns
    assert "heat_deg_interaction" in result.columns
    assert "wet_stint" in result.columns
    assert "abs_sector_delta" in result.columns


def test_tyre_age_sq_correct():
    df = make_sample_df(10)
    result = engineer_features(df)
    expected = df["tyre_age"] ** 2
    np.testing.assert_array_equal(result["tyre_age_sq"].values, expected.values)


def test_heat_deg_interaction_correct():
    df = make_sample_df(10)
    result = engineer_features(df)
    expected = (df["track_temperature"] * df["tyre_age"] / 100.0)
    np.testing.assert_array_almost_equal(result["heat_deg_interaction"].values, expected.values)


def test_auc_threshold_value():
    assert AUC_THRESHOLD == 0.82


def test_feature_cols_count():
    assert len(FEATURE_COLS) == 7


def test_all_base_features_present():
    expected = ["tyre_age", "stint_number", "gap_to_leader",
                 "air_temperature", "track_temperature", "rainfall", "sector_delta"]
    for f in expected:
        assert f in FEATURE_COLS
