variable "project" { type = string }
variable "environment" { type = string }
variable "account_id" { type = string }

terraform {
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}
