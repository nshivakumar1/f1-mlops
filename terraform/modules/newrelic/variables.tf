variable "project" { type = string }
variable "environment" { type = string }
variable "s3_bucket" { type = string }

variable "newrelic_license_key" {
  type      = string
  sensitive = true
}
