variable "aws_region" {
  description = "Region label to pass to the provider. LocalStack doesn't have real regions -- any valid-looking value works -- but this keeps parity with ../terraform/variables.tf."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Used as a prefix/tag, matching ../terraform/variables.tf."
  type        = string
  default     = "cashpulse"
}
