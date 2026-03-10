data "aws_caller_identity" "current" {}

resource "aws_opensearch_domain" "f1" {
  domain_name    = "${var.project}-logs"
  engine_version = "OpenSearch_2.11"

  cluster_config {
    instance_type  = "t3.small.search"
    instance_count = 1
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = 10
  }

  encrypt_at_rest { enabled = true }
  node_to_node_encryption { enabled = true }
  domain_endpoint_options { enforce_https = true }

  advanced_security_options {
    enabled                        = true
    anonymous_auth_enabled         = false
    internal_user_database_enabled = true
    master_user_options {
      master_user_name     = "f1admin"
      master_user_password = random_password.opensearch_admin.result
    }
  }
}

resource "random_password" "opensearch_admin" {
  length  = 16
  special = true
}

resource "aws_secretsmanager_secret" "opensearch_admin" {
  name = "f1-mlops/opensearch-admin"
}

resource "aws_secretsmanager_secret_version" "opensearch_admin" {
  secret_id     = aws_secretsmanager_secret.opensearch_admin.id
  secret_string = jsonencode({
    username = "f1admin"
    password = random_password.opensearch_admin.result
    endpoint = "https://${aws_opensearch_domain.f1.endpoint}"
  })
}

# Access policy — allow firehose and the account to write
resource "aws_opensearch_domain_policy" "f1" {
  domain_name = aws_opensearch_domain.f1.domain_name
  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }
        Action    = "es:*"
        Resource  = "${aws_opensearch_domain.f1.arn}/*"
      }
    ]
  })
}
