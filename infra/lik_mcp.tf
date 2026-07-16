# lik-mcp: Lightsail Container Service + deployment. The service is created first (its
# public `url` is what OAuth registrations are keyed to); the deployment version is
# created only once an image ref is supplied (var.lik_mcp_image), so a full apply before
# the image is pushed simply skips it.

resource "aws_lightsail_container_service" "lik_mcp" {
  name  = "lik-mcp-prod"
  power = var.container_power
  scale = var.container_scale

  # Attach the custom domain + its Lightsail-managed certificate when configured (see the
  # matching note in lik_ui.tf). Without this, Terraform removes a console-attached domain.
  dynamic "public_domain_names" {
    for_each = local.mcp_custom_host != "" ? [1] : []
    content {
      certificate {
        certificate_name = "lik-mcp-prod-cert"
        domain_names     = [local.mcp_custom_host]
      }
    }
  }
}

locals {
  # Host parsed straight from the custom-domain var (empty when unset); used for the domain
  # attachment above, kept separate from mcp_host to avoid a cycle through the resource.
  mcp_custom_host = var.mcp_custom_domain_url != "" ? replace(trimsuffix(var.mcp_custom_domain_url, "/"), "https://", "") : ""

  # Prefer the custom domain when set; otherwise the Lightsail-assigned HTTPS URL (the
  # service's `.url` never returns the attached custom domain — see variables.tf). Trailing
  # slash + scheme are stripped for host derivation below.
  mcp_url_base = var.mcp_custom_domain_url != "" ? trimsuffix(var.mcp_custom_domain_url, "/") : trimsuffix(aws_lightsail_container_service.lik_mcp.url, "/")
  mcp_host     = replace(local.mcp_url_base, "https://", "")
  # The MCP endpoint path is /mcp; this exact string is lik-mcp's resource identifier and
  # must equal lik-ui's LIK_UI_LIKMCP_RESOURCE_URL (wired in lik_ui.tf).
  mcp_resource_url = "${local.mcp_url_base}/mcp"
}

resource "aws_lightsail_container_service_deployment_version" "lik_mcp" {
  count        = var.lik_mcp_image == "" ? 0 : 1
  service_name = aws_lightsail_container_service.lik_mcp.name

  container {
    container_name = "lik-mcp"
    image          = var.lik_mcp_image

    environment = {
      LIK_ENV                 = "prod"
      LIK_DB_HOST             = aws_lightsail_database.main.master_endpoint_address
      LIK_DB_PORT             = tostring(aws_lightsail_database.main.master_endpoint_port)
      LIK_DB_NAME             = var.db_mcp_database_name
      LIK_DB_USER             = var.db_master_username
      LIK_DB_PASSWORD         = aws_ssm_parameter.db_master_password.value
      LIK_DB_SSLMODE          = "require"
      LIK_OAUTH_CLIENT_ID     = data.aws_ssm_parameter.mcp["LIK_OAUTH_CLIENT_ID"].value
      LIK_RESOURCE_SERVER_URL = local.mcp_resource_url
      LIK_HTTP_ALLOWED_HOSTS  = local.mcp_host
    }

    ports = {
      "8000" = "HTTP"
    }
  }

  public_endpoint {
    container_name = "lik-mcp"
    container_port = 8000

    # lik-mcp has no unauthenticated health route; the only path is /mcp, which returns
    # 401 under prod auth. The default success range 200-499 treats that 401 as "alive".
    health_check {
      path          = "/mcp"
      success_codes = "200-499"
    }
  }
}
