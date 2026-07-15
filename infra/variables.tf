variable "aws_region" {
  description = "AWS region for all production resources. Must stay us-east-1 (see plan D0)."
  type        = string
  default     = "us-east-1"
}

variable "ssm_prefix" {
  description = "Path prefix for all SSM parameters, no trailing slash."
  type        = string
  default     = "/ik-arch/prod"
}

# --- Database ---------------------------------------------------------------

variable "db_blueprint_id" {
  description = <<-EOT
    Lightsail Postgres engine blueprint. postgres_18 matches local dev (postgres:18.4)
    and is >= 15, so rds.force_ssl defaults to 1 (TLS enforced server-side). Verify the
    list stays current with: aws lightsail get-relational-database-blueprints.
  EOT
  type        = string
  default     = "postgres_18"
}

variable "db_bundle_id" {
  description = "Lightsail DB size. micro_2_0 is the smallest (1GB/2vCPU, ~$15/mo). Non-HA."
  type        = string
  default     = "micro_2_0"
}

variable "db_master_username" {
  description = "Master DB user. Both services connect as this user to their own database."
  type        = string
  default     = "lik"
}

variable "db_mcp_database_name" {
  description = "Database name for lik-mcp (the instance's master database)."
  type        = string
  default     = "likdb"
}

variable "db_ui_database_name" {
  description = "Database name for lik-ui. Created as a second DB on the instance during schema init."
  type        = string
  default     = "likuidb"
}

# --- Container services -----------------------------------------------------

variable "container_power" {
  description = "Lightsail container service power (nano is smallest/cheapest)."
  type        = string
  default     = "nano"
}

variable "container_scale" {
  description = "Number of container service nodes."
  type        = number
  default     = 1
}

variable "lik_mcp_image" {
  description = <<-EOT
    Lightsail-registered image ref for lik-mcp, e.g. ":lik-mcp-prod.app.3". Produced by
    `aws lightsail push-container-image` (run in CI). Required for the deployment apply;
    leave unset for the DB+services bootstrap apply (which is -target'd and does not read it).
  EOT
  type        = string
  default     = ""
}

variable "lik_ui_image" {
  description = "Lightsail-registered image ref for lik-ui, e.g. ':lik-ui-prod.app.3'. See lik_mcp_image."
  type        = string
  default     = ""
}

# --- GitHub OIDC (CI image push) --------------------------------------------

variable "github_org" {
  description = "GitHub org that owns the repo (OIDC trust subject)."
  type        = string
  default     = "navapbc"
}

variable "github_repo" {
  description = "GitHub repo name (OIDC trust subject)."
  type        = string
  default     = "leverage-inst-knowl"
}

variable "github_branch" {
  description = "Branch allowed to assume the CI push role."
  type        = string
  default     = "main"
}
