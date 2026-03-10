variable "project" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "account_id" { type = string }
variable "role_arn" { type = string }
variable "s3_bucket" { type = string }
variable "github_owner" { type = string }
variable "github_repo" { type = string }
variable "github_branch" { type = string default = "main" }
