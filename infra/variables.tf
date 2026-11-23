variable "region" {
  description = "AWS region for the signaler."
  type        = string
  default     = "us-west-2"
}

variable "email_to" {
  description = "Verified SES recipient identity."
  type        = string
  default     = "coleperschon38@gmail.com"
}

variable "email_from" {
  description = "Verified SES sender identity."
  type        = string
  default     = "coleperschon38@gmail.com"
}

variable "serpapi_api_key" {
  description = "SerpApi API key."
  type        = string
  sensitive   = true
}

variable "lambda_zip" {
  description = "Path to the deployment artifact produced by scripts/build.sh."
  type        = string
  default     = "../build/ski_signal.zip"
}
