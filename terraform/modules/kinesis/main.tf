# Kinesis Firehose — S3 delivery (ELK stack on EC2 reads from S3 via Logstash S3 input)
# OpenSearch destination removed: replaced by self-hosted ELK on EC2.

resource "aws_kinesis_firehose_delivery_stream" "inference_logs" {
  name        = "${var.project}-inference-logs"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn           = var.role_arn
    bucket_arn         = "arn:aws:s3:::${var.s3_bucket}"
    prefix             = "logs/inference/firehose/"
    buffering_size     = 5
    buffering_interval = 60
    compression_format = "GZIP"

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_inference.name
      log_stream_name = "DeliveryErrors"
    }
  }
}

resource "aws_kinesis_firehose_delivery_stream" "training_logs" {
  name        = "${var.project}-training-logs"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn           = var.role_arn
    bucket_arn         = "arn:aws:s3:::${var.s3_bucket}"
    prefix             = "logs/training/firehose/"
    buffering_size     = 5
    buffering_interval = 60
    compression_format = "GZIP"
  }
}

resource "aws_cloudwatch_log_group" "firehose_inference" {
  name              = "/aws/kinesisfirehose/${var.project}-inference-logs"
  retention_in_days = 7
}
