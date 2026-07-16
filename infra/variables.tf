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

# --- Custom domains (optional) ----------------------------------------------
# A Lightsail container service's `.url` attribute ALWAYS returns the default
# `...cs.amazonlightsail.com` address, even after a custom domain is attached — there is no
# provider attribute that flips it. So the URL-derived env values (APP_BASE_URL,
# RESOURCE_SERVER_URL, ALLOWED_HOSTS) do NOT follow a custom domain on their own. Set these
# to the friendly base URLs (scheme + host, no trailing slash, no `/mcp` suffix) to make the
# apps advertise the custom domain. Leave empty to use the Lightsail default URL (the
# bootstrap / pre-domain state). Only flip these once the custom domain is validated and
# attached (see docs/deploy-runbook.md "Custom-domain migration").

variable "ui_custom_domain_url" {
  description = "Custom base URL for lik-ui, e.g. \"https://ui.lik.navapbc.com\". Empty = use the Lightsail default URL."
  type        = string
  default     = ""
}

variable "mcp_custom_domain_url" {
  description = "Custom base URL for lik-mcp, e.g. \"https://mcp.lik.navapbc.com\". The /mcp path is appended. Empty = use the Lightsail default URL."
  type        = string
  default     = ""
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
  description = "Branch allowed to deploy to the GitHub environment (enforced by the env's branch policy, not the OIDC sub)."
  type        = string
  default     = "main"
}

variable "github_environment" {
  description = <<-EOT
    GitHub Environment the CI job runs in. Because the workflow job sets `environment: prod`,
    the OIDC token's `sub` is `repo:ORG/REPO:environment:<this>` (NOT the branch form), so the
    trust policy matches on environment. Branch restriction is enforced by the environment's
    deployment branch policy (set to `main`), not by the sub.
  EOT
  type        = string
  default     = "prod"
}
