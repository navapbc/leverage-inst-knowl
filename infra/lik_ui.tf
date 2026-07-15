# lik-ui: Lightsail Container Service + deployment. Same shape as lik-mcp. lik-ui has a
# real unauthenticated health route (/healthz). Its LIK_UI_LIKMCP_* connection values are
# wired to structurally satisfy the cross-service equality constraints:
#   LIK_UI_LIKMCP_CLIENT_ID   == lik-mcp's LIK_OAUTH_CLIENT_ID   (same SSM param)
#   LIK_UI_LIKMCP_RESOURCE_URL == lik-mcp's LIK_RESOURCE_SERVER_URL (same derived value)

resource "aws_lightsail_container_service" "lik_ui" {
  name  = "lik-ui-prod"
  power = var.container_power
  scale = var.container_scale
}

locals {
  ui_url_base = trimsuffix(aws_lightsail_container_service.lik_ui.url, "/")
  ui_host     = replace(local.ui_url_base, "https://", "")
}

resource "aws_lightsail_container_service_deployment_version" "lik_ui" {
  count        = var.lik_ui_image == "" ? 0 : 1
  service_name = aws_lightsail_container_service.lik_ui.name

  container {
    container_name = "lik-ui"
    image          = var.lik_ui_image

    environment = {
      LIK_UI_ENV         = "prod"
      LIK_UI_DB_HOST     = aws_lightsail_database.main.master_endpoint_address
      LIK_UI_DB_PORT     = tostring(aws_lightsail_database.main.master_endpoint_port)
      LIK_UI_DB_NAME     = var.db_ui_database_name
      LIK_UI_DB_USER     = var.db_master_username
      LIK_UI_DB_PASSWORD = aws_ssm_parameter.db_master_password.value
      LIK_UI_DB_SSLMODE  = "require"

      # Public base URL: OAuth callbacks are derived from it and the session cookie is
      # https-only outside local/test, so this must be the real HTTPS URL.
      LIK_UI_APP_BASE_URL       = local.ui_url_base
      LIK_UI_HTTP_ALLOWED_HOSTS = local.ui_host

      LIK_UI_SESSION_SECRET          = data.aws_ssm_parameter.ui["LIK_UI_SESSION_SECRET"].value
      LIK_UI_APP_OAUTH_CLIENT_ID     = data.aws_ssm_parameter.ui["LIK_UI_APP_OAUTH_CLIENT_ID"].value
      LIK_UI_APP_OAUTH_CLIENT_SECRET = data.aws_ssm_parameter.ui["LIK_UI_APP_OAUTH_CLIENT_SECRET"].value

      # lik-mcp connection — client id/resource url reused from lik-mcp to guarantee equality.
      LIK_UI_LIKMCP_CLIENT_ID     = data.aws_ssm_parameter.mcp["LIK_OAUTH_CLIENT_ID"].value
      LIK_UI_LIKMCP_CLIENT_SECRET = data.aws_ssm_parameter.ui["LIK_UI_LIKMCP_CLIENT_SECRET"].value
      LIK_UI_LIKMCP_RESOURCE_URL  = local.mcp_resource_url

      LIK_UI_GDRIVEMCP_CLIENT_ID     = data.aws_ssm_parameter.ui["LIK_UI_GDRIVEMCP_CLIENT_ID"].value
      LIK_UI_GDRIVEMCP_CLIENT_SECRET = data.aws_ssm_parameter.ui["LIK_UI_GDRIVEMCP_CLIENT_SECRET"].value
      LIK_UI_GDRIVEMCP_RESOURCE_URL  = data.aws_ssm_parameter.ui["LIK_UI_GDRIVEMCP_RESOURCE_URL"].value

      LIK_UI_GITHUB_CLIENT_ID     = data.aws_ssm_parameter.ui["LIK_UI_GITHUB_CLIENT_ID"].value
      LIK_UI_GITHUB_CLIENT_SECRET = data.aws_ssm_parameter.ui["LIK_UI_GITHUB_CLIENT_SECRET"].value
      LIK_UI_GITHUB_RESOURCE_URL  = data.aws_ssm_parameter.ui["LIK_UI_GITHUB_RESOURCE_URL"].value

      LIK_UI_ANTHROPIC_API_KEY = data.aws_ssm_parameter.ui["LIK_UI_ANTHROPIC_API_KEY"].value
      LIK_UI_AGENTS_CONFIG     = data.aws_ssm_parameter.ui["LIK_UI_AGENTS_CONFIG"].value
    }

    ports = {
      "8001" = "HTTP"
    }
  }

  public_endpoint {
    container_name = "lik-ui"
    container_port = 8001

    health_check {
      path          = "/healthz"
      success_codes = "200-399"
    }
  }
}
