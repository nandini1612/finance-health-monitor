# ============================================================================
# CashPulse Cloud Edition - infrastructure
#
# Provisions exactly two things, both sized as small/cheap as AWS allows --
# check your AWS account's actual Free Tier / Credits status in the Billing
# Console before running this (see cloud/README.md cost-safety section;
# AWS restructured its free tier in mid-2025 and terms vary by account age):
#   1. An RDS Postgres instance   -- the managed DBMS (raw + analytics + ml schemas)
#   2. An S3 bucket               -- a landing zone for raw file drops, the
#                                     "data lake" piece real pipelines usually have
#                                     alongside a database
#
# Deliberately NOT provisioned here: a data warehouse (Redshift/Snowflake).
# Redshift Serverless's "free trial" is time-boxed (compute-hours over ~2
# months) and can incur charges after that or if you exceed it, which
# conflicts with the "strictly free-tier" choice made for this project.
# Postgres is used as both the operational and analytical store instead --
# a completely normal pattern for a project at this scale (dbt runs
# directly against Postgres); see cloud/README.md for how to swap in
# Redshift later once you're comfortable monitoring a bill.
#
# Run (after `cp terraform.tfvars.example terraform.tfvars` and filling it in):
#   terraform init
#   terraform validate
#   terraform plan
#   terraform apply
#
# When you're done for the day/week: `terraform destroy`. Whether you're
# on AWS's 6-month/$200-credit new-account plan or an older 12-months-free
# account, leaving RDS running 24/7 burns through that allowance faster
# than using it only while you're actively working -- see the cost-safety
# checklist in cloud/README.md before you start.
# ============================================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# --- Use the account's default VPC rather than provisioning a new one.
# Simpler and free either way, but this avoids a second thing to tear down.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# --- Security group: only your own IP can reach Postgres. Never widen this.
resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "Allow Postgres from a single trusted IP only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Postgres from my IP"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.my_ip_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project_name }
}

resource "aws_db_subnet_group" "rds" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = data.aws_subnets.default.ids
  tags       = { Project = var.project_name }
}

# --- The database itself.
resource "aws_db_instance" "cashpulse" {
  identifier     = "${var.project_name}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = var.db_allocated_storage_gb # pin storage -- disable autoscaling so a runaway load can't grow past free tier

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.rds.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = true # needed so your laptop / Power BI / Tableau can reach it directly; locked down by the security group above

  multi_az                = false # multi-AZ is NOT free-tier eligible -- keep this false
  storage_encrypted       = true
  backup_retention_period = 1 # minimal backups; raise if this becomes more than a learning project
  skip_final_snapshot     = true # fine for a portfolio project; a real production DB would not do this
  deletion_protection     = false # so `terraform destroy` actually works when you're done

  tags = { Project = var.project_name }
}

# --- S3 landing zone. Bucket names are globally unique, hence the suffix.
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "raw_landing" {
  bucket        = "${var.project_name}-raw-landing-${random_id.bucket_suffix.hex}"
  force_destroy = true # lets `terraform destroy` remove the bucket even if it has objects in it

  tags = { Project = var.project_name }
}

resource "aws_s3_bucket_public_access_block" "raw_landing" {
  bucket                  = aws_s3_bucket.raw_landing.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "raw_landing" {
  bucket = aws_s3_bucket.raw_landing.id

  rule {
    id     = "expire-old-raw-drops"
    status = "Enabled"
    filter {}
    expiration {
      days = 30 # this is a landing zone, not long-term storage -- dbt/Postgres holds the durable copy
    }
  }
}
