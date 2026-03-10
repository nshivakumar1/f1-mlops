# Firehose: Lambda inference logs → OpenSearch
resource "aws_kinesis_firehose_delivery_stream" "inference_logs" {
  name        = "${var.project}-inference-logs"
  destination = "opensearch"

  opensearch_configuration {
    domain_arn            = var.opensearch_arn
    role_arn              = var.role_arn
    index_name            = "f1-inference"
    index_rotation_period = "OneDay"
    buffering_size        = 5
    buffering_interval    = 60

    s3_configuration {
      role_arn           = var.role_arn
      bucket_arn         = "arn:aws:s3:::${var.s3_bucket}"
      prefix             = "logs/inference/"
      buffering_size     = 5
      buffering_interval = 300
      compression_format = "GZIP"
    }

    processing_configuration {
      enabled = false
    }

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = "/aws/kinesisfirehose/${var.project}-inference-logs"
      log_stream_name = "DeliveryErrors"
    }
  }
}

# Firehose: Training / pipeline logs → OpenSearch
resource "aws_kinesis_firehose_delivery_stream" "training_logs" {
  name        = "${var.project}-training-logs"
  destination = "opensearch"

  opensearch_configuration {
    domain_arn            = var.opensearch_arn
    role_arn              = var.role_arn
    index_name            = "f1-training"
    index_rotation_period = "OneWeek"
    buffering_size        = 5
    buffering_interval    = 60

    s3_configuration {
      role_arn           = var.role_arn
      bucket_arn         = "arn:aws:s3:::${var.s3_bucket}"
      prefix             = "logs/training/"
      buffering_size     = 5
      buffering_interval = 300
      compression_format = "GZIP"
    }

    processing_configuration {
      enabled = false
    }
  }
}

resource "aws_cloudwatch_log_group" "firehose_inference" {
  name              = "/aws/kinesisfirehose/${var.project}-inference-logs"
  retention_in_days = 7
}
