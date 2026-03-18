variable "project" { type = string }
variable "environment" { type = string }
variable "s3_bucket" { type = string }

variable "newrelic_license_key" {
  type      = string
  sensitive = true
}

variable "newrelic_account_id" {
  description = "New Relic account ID (used as ExternalId for cross-account role)"
  type        = string
}
