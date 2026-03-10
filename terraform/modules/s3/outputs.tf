output "data_bucket_name" { value = aws_s3_bucket.data.bucket }
output "data_bucket_arn"  { value = aws_s3_bucket.data.arn }
output "artifacts_bucket_name" { value = aws_s3_bucket.artifacts.bucket }
output "artifacts_bucket_arn"  { value = aws_s3_bucket.artifacts.arn }
output "tfstate_bucket_name"   { value = aws_s3_bucket.tfstate.bucket }
