# SageMaker Serverless Inference endpoint config for pitstop model
resource "aws_sagemaker_endpoint_configuration" "pitstop" {
  name = "${var.project}-pitstop-serverless-config"

  production_variants {
    variant_name           = "dry-race-v1"
    model_name             = aws_sagemaker_model.pitstop_dry.name
    serverless_config {
      memory_size_in_mb = 2048
      max_concurrency   = 10
    }
  }
}

resource "aws_sagemaker_model" "pitstop_dry" {
  name               = "${var.project}-pitstop-dry-v1"
  execution_role_arn = var.role_arn

  primary_container {
    image          = "${var.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.project}-training:latest"
    model_data_url = "s3://${var.s3_bucket}/models/pitstop/dry-race-v1/model.tar.gz"
    environment = {
      SAGEMAKER_CONTAINER_LOG_LEVEL = "20"
      SAGEMAKER_PROGRAM              = "inference.py"
    }
  }

  lifecycle {
    ignore_changes = [primary_container[0].model_data_url]
  }
}

resource "aws_sagemaker_endpoint" "pitstop" {
  name                 = "${var.project}-pitstop-endpoint"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.pitstop.name

  lifecycle {
    ignore_changes = [endpoint_config_name]
  }
}

# SageMaker Feature Store — offline only (S3-backed, no DynamoDB)
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
