# ── New Relic AWS Account Linking ─────────────────────────────────────────────
# IAM role that New Relic assumes to poll CloudWatch for entity synthesis.
# This enables Lambda/SageMaker to appear as proper entities in NR (not just raw metrics).
# After terraform apply, register the role ARN in:
#   NR UI → Infrastructure → AWS → Add AWS account → use role ARN below

resource "aws_iam_role" "newrelic_integration" {
  name = "${var.project}-newrelic-integration"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = {
        # New Relic's AWS account ID for cross-account role assumption
        AWS = "arn:aws:iam::754728514883:root"
      }
      Condition = {
        StringEquals = { "sts:ExternalId" = var.newrelic_account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "newrelic_readonly" {
  role       = aws_iam_role.newrelic_integration.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# ── New Relic Observability Integration ───────────────────────────────────────
# CloudWatch Metric Streams → Kinesis Firehose → New Relic
# Streams Lambda, SageMaker, and custom F1MLOps metrics in near-real-time

# IAM: CloudWatch Metric Stream → Firehose
resource "aws_iam_role" "metric_stream" {
  name = "${var.project}-cw-metric-stream-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "streams.metrics.cloudwatch.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "metric_stream" {
  name = "${var.project}-metric-stream-policy"
  role = aws_iam_role.metric_stream.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["firehose:PutRecord", "firehose:PutRecordBatch"]
      Resource = aws_kinesis_firehose_delivery_stream.newrelic.arn
    }]
  })
}

# IAM: Firehose → New Relic HTTP endpoint (S3 backup for failed deliveries)
resource "aws_iam_role" "firehose_newrelic" {
  name = "${var.project}-firehose-nr-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "firehose.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "firehose_newrelic" {
  name = "${var.project}-firehose-nr-policy"
  role = aws_iam_role.firehose_newrelic.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:AbortMultipartUpload",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:PutObject"
      ]
      Resource = [
        "arn:aws:s3:::${var.s3_bucket}",
        "arn:aws:s3:::${var.s3_bucket}/*"
      ]
    }]
  })
}

# Kinesis Firehose → New Relic CloudWatch Metrics ingest endpoint
resource "aws_kinesis_firehose_delivery_stream" "newrelic" {
  name        = "${var.project}-newrelic-metrics"
  destination = "http_endpoint"

  http_endpoint_configuration {
    url                = "https://aws-api.newrelic.com/cloudwatch-metrics/v1"
    name               = "New Relic CloudWatch Metrics"
    access_key         = var.newrelic_license_key
    buffering_size     = 1
    buffering_interval = 60
    role_arn           = aws_iam_role.firehose_newrelic.arn
    s3_backup_mode     = "FailedDataOnly"

    s3_configuration {
      role_arn           = aws_iam_role.firehose_newrelic.arn
      bucket_arn         = "arn:aws:s3:::${var.s3_bucket}"
      prefix             = "newrelic-metrics-backup/"
      compression_format = "GZIP"
    }

    request_configuration {
      content_encoding = "GZIP"
    }
  }
}

# CloudWatch Metric Stream → Firehose → New Relic
# Covers Lambda, SageMaker, custom F1MLOps metrics, and billing in near-real-time
resource "aws_cloudwatch_metric_stream" "newrelic" {
  name          = "${var.project}-newrelic-stream"
  role_arn      = aws_iam_role.metric_stream.arn
  firehose_arn  = aws_kinesis_firehose_delivery_stream.newrelic.arn
  output_format = "opentelemetry0.7"

  include_filter {
    namespace = "AWS/Lambda"
  }

  include_filter {
    namespace = "AWS/SageMaker"
  }

  include_filter {
    namespace = "F1MLOps/Models"
  }

  include_filter {
    namespace = "AWS/Billing"
  }
}
