output "rds_endpoint" {
  description = "Host:port to connect to. Combine with db_name/db_username/your password to build DATABASE_URL."
  value       = aws_db_instance.cashpulse.address
}

output "rds_port" {
  value = aws_db_instance.cashpulse.port
}

output "database_url_template" {
  description = "Copy this into cloud/.env and fill in your password -- never put the real password in Terraform outputs/state that you might paste somewhere."
  value       = "postgresql://${var.db_username}:<YOUR_PASSWORD>@${aws_db_instance.cashpulse.address}:${aws_db_instance.cashpulse.port}/${var.db_name}"
}

output "s3_raw_landing_bucket" {
  value = aws_s3_bucket.raw_landing.bucket
}
