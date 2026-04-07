"""Unit tests for pitstop ML model training utilities."""
import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../ml/training/pitstop"))

from train import engineer_features, RAW_FEATURES, ALL_FEATURES, TARGET_COL, AUC_THRESHOLD


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


def make_sample_df_with_session(n: int = 100) -> pd.DataFrame:
    """Sample df with session/driver/lap columns needed for rolling features."""
    np.random.seed(42)
    df = pd.DataFrame({
        "session_key": [1] * n,
        "driver_number": ([1] * (n // 2)) + ([2] * (n - n // 2)),
        "lap_number": list(range(1, n // 2 + 1)) + list(range(1, n - n // 2 + 1)),
        "tyre_age": np.random.randint(0, 40, n),
        "stint_number": np.random.randint(1, 4, n),
        "gap_to_leader": np.random.uniform(0, 60, n),
        "air_temperature": np.random.uniform(20, 40, n),
        "track_temperature": np.random.uniform(30, 60, n),
        "rainfall": np.random.randint(0, 2, n),
        "sector_delta": np.random.uniform(-2, 2, n),
        "tyre_compound": np.random.choice(["SOFT", "MEDIUM", "HARD"], n),
        "pitstop_within_3_laps": np.random.randint(0, 2, n),
    })
    return df


def test_engineer_features_adds_derived_columns():
    df = make_sample_df_with_session(50)
    result = engineer_features(df)
    for col in ["tyre_age_sq", "heat_deg_interaction", "wet_stint", "abs_sector_delta"]:
        assert col in result.columns, f"Missing derived column: {col}"


def test_engineer_features_adds_rolling_columns():
    df = make_sample_df_with_session(50)
    result = engineer_features(df)
    for col in ["deg_rate", "gap_trend", "rolling_sector_delta_5", "tyre_stress_index"]:
        assert col in result.columns, f"Missing rolling column: {col}"


def test_engineer_features_adds_compound_columns():
    df = make_sample_df_with_session(50)
    result = engineer_features(df)
    for col in ["compound_soft", "compound_medium", "compound_hard"]:
        assert col in result.columns, f"Missing compound column: {col}"


def test_tyre_age_sq_correct():
    df = make_sample_df_with_session(10)
    result = engineer_features(df)
    np.testing.assert_array_equal(result["tyre_age_sq"].values, (df["tyre_age"] ** 2).values)


def test_heat_deg_interaction_correct():
    df = make_sample_df_with_session(10)
    result = engineer_features(df)
    expected = df["track_temperature"] * df["tyre_age"] / 100.0
    np.testing.assert_array_almost_equal(result["heat_deg_interaction"].values, expected.values)


def test_compound_one_hot_exclusive():
    df = make_sample_df_with_session(30)
    result = engineer_features(df)
    # A SOFT row must have compound_soft=1 and others=0
    soft_rows = result[result["tyre_compound"].str.upper() == "SOFT"]
    if not soft_rows.empty:
        assert (soft_rows["compound_soft"] == 1).all()
        assert (soft_rows["compound_medium"] == 0).all()
        assert (soft_rows["compound_hard"] == 0).all()


def test_auc_threshold_value():
    assert AUC_THRESHOLD == 0.90


def test_raw_feature_cols_count():
    assert len(RAW_FEATURES) == 7


def test_all_features_count():
    assert len(ALL_FEATURES) == 18


def test_all_base_features_present():
    expected = ["tyre_age", "stint_number", "gap_to_leader",
                 "air_temperature", "track_temperature", "rainfall", "sector_delta"]
    for f in expected:
        assert f in RAW_FEATURES
