# New, empty Lightsail managed Postgres in us-east-1. One instance hosts two databases:
# the master DB (lik-mcp) plus a second DB (lik-ui) created during schema init. Public
# mode is on (Container Services cannot reach the private endpoint); TLS is enforced
# server-side by default on Postgres >= 15 (rds.force_ssl=1) and required client-side.

resource "random_password" "db_master" {
  length = 32
  # Lightsail master_password forbids '/', '"', and '@'. Restrict the special set to a
  # safe subset rather than using the default (which includes all three).
  override_special = "!#$%^&*()-_=+[]{}<>:?"
}

resource "aws_lightsail_database" "main" {
  relational_database_name = "lik-prod-db"
  availability_zone        = "${var.aws_region}a"
  blueprint_id             = var.db_blueprint_id
  bundle_id                = var.db_bundle_id

  master_database_name = var.db_mcp_database_name
  master_username      = var.db_master_username
  master_password      = random_password.db_master.result

  publicly_accessible      = true
  backup_retention_enabled = true
  apply_immediately        = true

  # Draft mode: no production data yet, so skip the final snapshot on destroy.
  skip_final_snapshot = true
}

# Master password is the one secret Terraform authors (rather than reads). It lands in
# SSM as the source of truth and in encrypted state.
resource "aws_ssm_parameter" "db_master_password" {
  name  = "${var.ssm_prefix}/shared/DB_MASTER_PASSWORD"
  type  = "SecureString"
  value = random_password.db_master.result
}
