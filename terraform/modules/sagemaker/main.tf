# SageMaker Feature Store — offline only (S3-backed, no DynamoDB cost)
resource "aws_sagemaker_feature_group" "f1_features" {
  feature_group_name             = "${var.project}-race-features"
  record_identifier_feature_name = "driver_number"
  event_time_feature_name        = "event_time"
  role_arn                       = var.role_arn

  feature_definition {
    feature_name = "driver_number"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "event_time"
    feature_type = "String"
  }
  feature_definition {
    feature_name = "tyre_age"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "stint_number"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "gap_to_leader"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "air_temperature"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "track_temperature"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "rainfall"
    feature_type = "Integral"
  }
  feature_definition {
    feature_name = "sector_delta"
    feature_type = "Fractional"
  }

  offline_store_config {
    s3_storage_config {
      s3_uri = "s3://${var.s3_bucket}/features/"
    }
    disable_glue_table_creation = false
  }

  # No online_store_config — offline only to avoid DynamoDB cost
}

# NOTE: SageMaker model, endpoint_config, and endpoint are created by the
# SageMaker Training Pipeline after first model training (Day 2 seed + train).
# See scripts/deploy_endpoint.py for post-training endpoint creation.
