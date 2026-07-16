# Secret / environment-specific values are the source of truth in SSM Parameter Store.
# Terraform READS them here (it does not author them, except the DB password in
# database.tf). Populate these out-of-band before the deployment apply — see
# docs/deploy-runbook.md "Populate SSM". A missing parameter makes `terraform plan` fail
# with a clear "ParameterNotFound", which is the intended gate.
#
# URL-derived values (LIK_RESOURCE_SERVER_URL, *_ALLOWED_HOSTS, LIK_UI_APP_BASE_URL,
# LIK_UI_LIKMCP_RESOURCE_URL) are NOT stored here — they are computed from the container
# service URLs in lik_mcp.tf / lik_ui.tf, which structurally enforces the cross-service
# equality constraints.

locals {
  # lik-mcp secrets/config read from SSM.
  mcp_ssm_params = [
    "LIK_OAUTH_CLIENT_ID",
  ]

  # lik-ui secrets/config read from SSM. Note: LIK_UI_LIKMCP_CLIENT_ID is NOT here — it
  # must equal lik-mcp's LIK_OAUTH_CLIENT_ID, so lik_ui.tf reuses that param directly.
  ui_ssm_params = [
    "LIK_UI_SESSION_SECRET",
    "LIK_UI_APP_OAUTH_CLIENT_ID",
    "LIK_UI_APP_OAUTH_CLIENT_SECRET",
    "LIK_UI_LIKMCP_CLIENT_SECRET",
    "LIK_UI_GDRIVEMCP_CLIENT_ID",
    "LIK_UI_GDRIVEMCP_CLIENT_SECRET",
    "LIK_UI_GDRIVEMCP_RESOURCE_URL",
    "LIK_UI_GITHUB_CLIENT_ID",
    "LIK_UI_GITHUB_CLIENT_SECRET",
    "LIK_UI_GITHUB_RESOURCE_URL",
    "LIK_UI_SLACK_CLIENT_ID",
    "LIK_UI_SLACK_CLIENT_SECRET",
    "LIK_UI_SLACK_RESOURCE_URL",
    "LIK_UI_ANTHROPIC_API_KEY",
    "LIK_UI_AGENTS_CONFIG",
  ]
}

data "aws_ssm_parameter" "mcp" {
  for_each = toset(local.mcp_ssm_params)
  name     = "${var.ssm_prefix}/lik-mcp/${each.key}"
}

data "aws_ssm_parameter" "ui" {
  for_each = toset(local.ui_ssm_params)
  name     = "${var.ssm_prefix}/lik-ui/${each.key}"
}
