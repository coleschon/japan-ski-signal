terraform {
  required_version = ">= 1.10.0"
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_caller_identity" "current" {}

locals {
  function_name = "japan-ski-signal"
  table_name    = "japan-ski-signal"
  bucket_name   = "${data.aws_caller_identity.current.account_id}-japan-ski-signal"
  log_group     = "/aws/lambda/${local.function_name}"
}

resource "aws_dynamodb_table" "signal" {
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }
}

resource "aws_s3_bucket" "snapshots" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "snapshots" {
  bucket                  = aws_s3_bucket.snapshots.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id

  rule {
    id     = "expire-raw-snapshots"
    status = "Enabled"

    expiration {
      days = 90
    }
  }
}

resource "aws_ses_email_identity" "recipient" {
  email = var.email_to
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = local.log_group
  retention_in_days = 14
}

resource "aws_iam_role" "lambda" {
  name = "${local.function_name}-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${local.function_name}-runtime"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Scan", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.signal.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.snapshots.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["ses:SendEmail"]
        Resource = aws_ses_email_identity.recipient.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "signal" {
  function_name    = local.function_name
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "ski_signal.handler.handler"
  filename         = var.lambda_zip
  source_code_hash = filebase64sha256(var.lambda_zip)
  timeout          = 300
  memory_size      = 512

  environment {
    variables = {
      DYNAMODB_TABLE      = aws_dynamodb_table.signal.name
      RAW_SNAPSHOT_BUCKET = aws_s3_bucket.snapshots.bucket
      SERPAPI_API_KEY     = var.serpapi_api_key
      EMAIL_TO            = var.email_to
      EMAIL_FROM          = var.email_from
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda,
    aws_cloudwatch_log_group.lambda
  ]
}

resource "aws_iam_role" "scheduler" {
  name = "${local.function_name}-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "scheduler.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "${local.function_name}-invoke-lambda"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = aws_lambda_function.signal.arn
    }]
  })
}

resource "aws_scheduler_schedule" "daily" {
  name                         = local.function_name
  schedule_expression          = "cron(0 6 * * ? *)"
  schedule_expression_timezone = "America/Los_Angeles"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.signal.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({})
  }
  depends_on = [aws_iam_role_policy.scheduler]
}
