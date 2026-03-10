variable "project" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "account_id" { type = string }
variable "role_arn" { type = string }
variable "s3_bucket" { type = string }
variable "github_owner" { type = string }
variable "github_repo" { type = string }
variable "github_branch" {
  type    = string
  default = "main"
}

variable "codestar_connection_arn" {
  description = "ARN of an existing AVAILABLE CodeStar/CodeConnections GitHub connection"
  type        = string
  default     = ""
}
