"""
AWS Glue ETL Job — F1 Feature Engineering
PySpark script: raw Parquet → ML feature vectors
Config: G.1X worker, 2 DPUs, ~40 min runtime
"""
import sys
import json
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.sql.types import FloatType, IntegerType

# Job parameters
args = getResolvedOptions(sys.argv, [
    "JOB_NAME",
    "S3_BUCKET",
    "INPUT_PREFIX",
    "OUTPUT_PREFIX",
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

S3_BUCKET = args["S3_BUCKET"]
INPUT_PREFIX = args["INPUT_PREFIX"]
OUTPUT_PREFIX = args["OUTPUT_PREFIX"]

print(f"Reading from s3://{S3_BUCKET}/{INPUT_PREFIX}")
print(f"Writing to s3://{S3_BUCKET}/{OUTPUT_PREFIX}")


def load_raw_data():
    """Load all raw OpenF1 session data from S3."""
    return spark.read.parquet(f"s3://{S3_BUCKET}/{INPUT_PREFIX}*.parquet")


def build_pitstop_features(df):
    """
    Build pitstop prediction feature vectors.
    One row per driver per lap. Target: pitstop_within_3_laps.
    """
    driver_lap_window = Window.partitionBy("driver_number", "session_key").orderBy("lap_number")

    # Feature: tyre_age — laps since last pit or session start
    df = df.withColumn(
        "tyre_age",
        F.col("lap_number") - F.last("pit_lap", ignorenulls=True).over(
            driver_lap_window.rowsBetween(Window.unboundedPreceding, 0)
        )
    ).fillna({"tyre_age": 0})

    # Feature: stint_number
    df = df.withColumn(
        "stint_number",
        F.sum(F.when(F.col("did_pit") == 1, 1).otherwise(0)).over(
            driver_lap_window.rowsBetween(Window.unboundedPreceding, 0)
        ) + 1
    )

    # Feature: gap_to_leader (seconds)
    df = df.withColumn(
        "gap_to_leader",
        F.col("gap_to_leader").cast(FloatType())
    )

    # Features: weather (broadcast join — same for all drivers per lap)
    # Already joined in raw data; just cast
    df = df.withColumn("air_temperature", F.col("air_temperature").cast(FloatType()))
    df = df.withColumn("track_temperature", F.col("track_temperature").cast(FloatType()))
    df = df.withColumn("rainfall", F.when(F.col("rainfall") == True, 1).otherwise(0).cast(IntegerType()))

    # Feature: sector_delta — current vs driver avg of last 3 laps
    last3_avg = F.avg("duration_sector_1").over(
        driver_lap_window.rowsBetween(-3, -1)
    )
    df = df.withColumn(
        "sector_delta",
        (F.col("duration_sector_1") - last3_avg).cast(FloatType())
    ).fillna({"sector_delta": 0.0})

    # Target: pitstop_within_3_laps
    next3_pit = F.max("did_pit").over(
        driver_lap_window.rowsBetween(1, 3)
    )
    df = df.withColumn("pitstop_within_3_laps", F.coalesce(next3_pit, F.lit(0)).cast(IntegerType()))

    return df.select(
        "session_key",
        "driver_number",
        "lap_number",
        "tyre_age",
        "stint_number",
        "gap_to_leader",
        "air_temperature",
        "track_temperature",
        "rainfall",
        "sector_delta",
        "pitstop_within_3_laps",
        "tyre_compound",
        "event_time",
    )


def build_position_features(df):
    """Build final position prediction feature vectors."""
    return df.select(
        "session_key",
        "driver_number",
        F.col("grid_position").cast(FloatType()),
        F.col("qualifying_delta_to_pole").cast(FloatType()),
        F.col("pit_count").cast(IntegerType()),
        F.col("avg_stint_length").cast(FloatType()),
        F.col("circuit_type"),
        F.col("team"),
        F.col("tyre_strategy"),
        F.col("weather_impact_score").cast(FloatType()),
        F.col("final_position").cast(IntegerType()),
    ).dropna(subset=["final_position"])


def build_safety_car_features(df):
    """Build safety car prediction feature vectors."""
    session_window = Window.partitionBy("session_key").orderBy("lap_number")

    # Gap variance across all drivers per lap
    gap_stats = df.groupBy("session_key", "lap_number").agg(
        F.stddev("gap_to_leader").alias("gap_variance"),
        F.count("*").alias("cars_on_track"),
    )

    df = df.join(gap_stats, on=["session_key", "lap_number"], how="left")

    # Rolling incident count
    df = df.withColumn(
        "incident_count_last_5_laps",
        F.sum(F.col("had_incident").cast(IntegerType())).over(
            session_window.rowsBetween(-5, -1)
        )
    ).fillna({"incident_count_last_5_laps": 0})

    return df.select(
        "session_key",
        "lap_number",
        F.col("gap_variance").cast(FloatType()),
        F.col("rainfall").cast(IntegerType()),
        F.col("incident_count_last_5_laps"),
        F.col("yellow_flag_count").cast(IntegerType()),
        F.col("circuit_id"),
        F.col("total_laps").cast(IntegerType()),
        F.col("safety_car_within_5_laps").cast(IntegerType()),
    ).dropDuplicates(["session_key", "lap_number"])


# Main ETL pipeline
print("Loading raw data...")
raw_df = load_raw_data()
raw_df.cache()
print(f"Raw rows: {raw_df.count()}")

print("Building pitstop features...")
pitstop_df = build_pitstop_features(raw_df)
pitstop_df.write.mode("overwrite").parquet(
    f"s3://{S3_BUCKET}/{OUTPUT_PREFIX}pitstop/"
)
print(f"Pitstop features written: {pitstop_df.count()} rows")

print("Building safety car features...")
sc_df = build_safety_car_features(raw_df)
sc_df.write.mode("overwrite").parquet(
    f"s3://{S3_BUCKET}/{OUTPUT_PREFIX}safety_car/"
)
print(f"Safety car features written: {sc_df.count()} rows")

print("Building position features...")
try:
    pos_df = build_position_features(raw_df)
    pos_df.write.mode("overwrite").parquet(
        f"s3://{S3_BUCKET}/{OUTPUT_PREFIX}position/"
    )
    print(f"Position features written: {pos_df.count()} rows")
except Exception as e:
    print(f"Position features skipped (missing columns): {e}")

print("Glue ETL complete.")
job.commit()
