variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name prefix"
  type        = string
  default     = "f1-mlops"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "account_id" {
  description = "AWS account ID"
  type        = string
  default     = "297997106614"
}

variable "alert_email" {
  description = "Email address for CloudWatch SNS alerts"
  type        = string
  default     = ""
}

variable "github_owner" {
  description = "GitHub repository owner"
  type        = string
  default     = "nshivakumar1"
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "f1-mlops"
}

variable "github_branch" {
  description = "GitHub branch to deploy from"
  type        = string
  default     = "main"
}
