output "firehose_stream_name"         { value = aws_kinesis_firehose_delivery_stream.inference_logs.name }
output "firehose_stream_arn"          { value = aws_kinesis_firehose_delivery_stream.inference_logs.arn }
output "training_firehose_stream_name" { value = aws_kinesis_firehose_delivery_stream.training_logs.name }
