resource "aws_s3_bucket" "data" {
  bucket = "${var.project}-data-${var.account_id}"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "${var.project}-artifacts-${var.account_id}"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = "${var.project}-tfstate-${var.account_id}"
}

resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "${var.project}-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    id     = "transition-to-ia"
    status = "Enabled"
    filter { prefix = "raw/" }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

# Folder structure via zero-byte objects
resource "aws_s3_object" "folders" {
  for_each = toset(["raw/", "processed/", "models/", "logs/", "features/"])
  bucket   = aws_s3_bucket.data.id
  key      = each.value
  content  = ""
}
