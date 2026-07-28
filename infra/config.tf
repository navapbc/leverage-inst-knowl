# Non-secret, environment-specific config that CI needs at run time. Terraform is the single
# source of truth for these values; it publishes them as plain String SSM parameters under
# ${ssm_prefix}/config/ so the deploy/cleanup workflows read them with the same
# `aws ssm get-parameter` they already use for secrets — without gaining Terraform-state access
# (state holds every secret in plaintext; see iam_github_oidc.tf). Values reference resource
# attributes / vars, never re-typed literals, so a CI copy can never drift from infra.
#
# Secrets do NOT belong here — those stay SecureString under /shared, /lik-mcp, /lik-ui (ssm.tf,
# database.tf). Developer CLI tooling (init_db) reads the richer `env_config` output instead
# (outputs.tf); it has state access already, so it doesn't need these params.

locals {
  # name (under ${ssm_prefix}/config/) => value. Add an entry when a workflow needs a new
  # non-secret, environment-specific value it currently hardcodes.
  config_ssm_params = {
    DB_INSTANCE    = aws_lightsail_database.main.relational_database_name
    LIK_UI_DB_NAME = var.db_ui_database_name
  }
}

resource "aws_ssm_parameter" "config" {
  for_each = local.config_ssm_params
  name     = "${var.ssm_prefix}/config/${each.key}"
  type     = "String"
  value    = each.value
}
