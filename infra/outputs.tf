output "lik_mcp_service_url" {
  description = "Public HTTPS URL of the lik-mcp container service (OAuth is keyed to this)."
  value       = aws_lightsail_container_service.lik_mcp.url
}

output "lik_mcp_resource_server_url" {
  description = "lik-mcp's LIK_RESOURCE_SERVER_URL (service URL + /mcp). Register OAuth against this."
  value       = local.mcp_resource_url
}

output "lik_ui_service_url" {
  description = "Public HTTPS URL of the lik-ui container service (LIK_UI_APP_BASE_URL)."
  value       = aws_lightsail_container_service.lik_ui.url
}

output "lik_ui_oauth_callback_urls" {
  description = "Redirect/callback URIs to register on the lik-ui OAuth clients."
  value = {
    app_login   = "${local.ui_url_base}/auth/callback"
    connections = "${local.ui_url_base}/connections/callback"
  }
}

output "db_endpoint" {
  description = "Lightsail Postgres endpoint (shared by both databases)."
  value = {
    host = aws_lightsail_database.main.master_endpoint_address
    port = aws_lightsail_database.main.master_endpoint_port
  }
}

output "github_image_push_role_arn" {
  description = "IAM role ARN for the GitHub Actions image-push workflow (configure-aws-credentials)."
  value       = aws_iam_role.github_image_push.arn
}

output "github_apply_role_arn" {
  description = "IAM role ARN for the GitHub Actions gated terraform-apply job. Set as the AWS_APPLY_ROLE_ARN repo/prod variable."
  value       = aws_iam_role.github_apply.arn
}
