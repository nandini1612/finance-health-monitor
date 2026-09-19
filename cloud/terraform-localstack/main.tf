# ============================================================================
# CashPulse Cloud Edition -- LocalStack (no AWS account, no card, $0)
#
# This is a parallel copy of ../terraform, aimed at LocalStack -- an
# open-source AWS API simulator you run on your own machine -- instead of
# real AWS. Use this path if you don't have (or don't want to hand over)
# a credit card for AWS account verification. See
# ../../INTEGRATION_PROOF_GUIDE.md for the full walkthrough.
#
# IMPORTANT -- read this before you assume this "provisions RDS":
#   LocalStack Community (the free tier) only MOCKS the RDS API surface --
#   `terraform apply` will succeed and `aws rds describe-db-instances` will
#   return a fake-but-valid-looking response, but there is no real Postgres
#   engine listening behind it. Actually running a database via LocalStack's
#   RDS emulation requires LocalStack Pro (paid). So this file provisions:
#     1. An S3 bucket -- genuinely real, fully working in the free Community
#        edition. You can actually put/get objects against it.
#     2. NOTHING for RDS. Don't fake it. Run a real Postgres instead --
#        `docker run postgres:16` on your own machine, or a native install
#        (same as this project's "local quickstart" tier already uses) --
#        and point DATABASE_URL at that. It's a real database, just not one
#        hosted on AWS. The dashboard's Integrations section is designed to
#        show this honestly as "Simulated" rather than claiming real AWS.
#
# This asymmetry (S3 real, RDS not) is a genuinely useful thing to
# understand and be able to explain -- it's the actual reason this file
# doesn't just mirror ../terraform/main.tf wholesale.
#
# Run:
#   1. Install & start LocalStack (needs Docker):
#        pip install localstack awscli-local
#        localstack start -d
#        curl http://localhost:4566/_localstack/health   # sanity check
#   2. terraform init && terraform apply    (no AWS credentials needed --
#      "test"/"test" below are LocalStack's standard placeholder values,
#      not real secrets)
#   3. awslocal s3 ls    -- confirms the bucket really exists
# ============================================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Dummy credentials -- LocalStack doesn't check these, but the AWS
  # provider still requires *something* to be set.
  access_key = "test"
  secret_key = "test"

  # Route every AWS API call at LocalStack's single endpoint instead of
  # real AWS, and skip the validation steps that assume a real account.
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true

  endpoints {
    s3 = "http://localhost:4566"
  }
}

# --- The one thing this actually, genuinely provisions.
resource "aws_s3_bucket" "raw_landing" {
  bucket        = "${var.project_name}-raw-landing-localstack"
  force_destroy = true

  tags = { Project = var.project_name, Mode = "localstack" }
}
