output "lambda_function_name" {
  value = aws_lambda_function.signal.function_name
}

output "snapshots_bucket" {
  value = aws_s3_bucket.snapshots.bucket
}

output "dynamodb_table" {
  value = aws_dynamodb_table.signal.name
}
