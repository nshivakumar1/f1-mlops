variable "project" { type = string }
variable "environment" { type = string }
variable "account_id" { type = string }
variable "aws_region" { type = string }
variable "lambda_function" { type = string }
variable "sagemaker_endpoint" { type = string }
variable "firehose_stream" { type = string }
variable "stepfunctions_arn" { type = string }
variable "alert_email" {
  type    = string
  default = ""
}
