variable "aws_region" {
  description = "AWS region to deploy into. Free-tier RDS/S3 allowances are per-account, not per-region, but stick to one region to keep this simple."
  type        = string
  default     = "us-east-1"
}

variable "db_instance_class" {
  description = "RDS instance class. db.t3.micro / db.t4g.micro are the smallest, cheapest classes RDS offers -- check your AWS account's actual Free Tier / Credits status (Billing Console) before assuming this is free; AWS's free-tier terms changed in mid-2025 (see cloud/README.md cost-safety section). Do not size this up without understanding what it costs."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "RDS storage in GB. Kept small deliberately -- verify current free-tier/credit coverage for storage in your AWS Billing Console before raising this."
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Database name created on the RDS instance."
  type        = string
  default     = "cashpulse"
}

variable "db_username" {
  description = "Master username for the RDS instance."
  type        = string
  default     = "cashpulse"
}

variable "db_password" {
  description = "Master password for the RDS instance. Set this via terraform.tfvars (gitignored) or TF_VAR_db_password -- never commit it."
  type        = string
  sensitive   = true
}

variable "my_ip_cidr" {
  description = "Your current public IP in CIDR form (e.g. 203.0.113.4/32), so the database's security group only ever accepts connections from you. Find yours with `curl ifconfig.me` and append /32. Never widen this to 0.0.0.0/0."
  type        = string
}

variable "project_name" {
  description = "Used as a prefix/tag on every resource, and to build a globally-unique S3 bucket name."
  type        = string
  default     = "cashpulse"
}
