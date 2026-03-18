variable "project" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "account_id" { type = string }
variable "lambda_role_arn" { type = string }
variable "s3_bucket" { type = string }
variable "sagemaker_endpoint" { type = string }
variable "sns_topic_arn" { type = string }

variable "newrelic_layer_arn" {
  description = "New Relic Lambda layer ARN for Python 3.12 (us-east-1)"
  type        = string
}

variable "newrelic_account_id" {
  description = "New Relic account ID"
  type        = string
}

