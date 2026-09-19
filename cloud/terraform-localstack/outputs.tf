output "s3_raw_landing_bucket" {
  value = aws_s3_bucket.raw_landing.bucket
}

output "note" {
  value = "This bucket is real (LocalStack Community fully supports S3). There is no RDS output here on purpose -- see the comment block at the top of main.tf. Run a real Postgres locally/in Docker for the pipeline to actually connect to."
}
