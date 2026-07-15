# GitHub Actions -> AWS via OIDC (no long-lived keys). The CI role is scoped to push
# container images only; `terraform apply` still runs locally under AWS_PROFILE=lik.
# Escalating this role to run apply in CI is the deferred full-auto-deploy work (plan N2/Q5).

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Scope to this repo + GitHub Environment. The workflow job runs with
    # `environment: prod`, so GitHub mints the token with sub = repo:ORG/REPO:environment:prod
    # (the branch `ref:` form is NOT present when a job uses an environment). Branch
    # restriction to `main` is enforced by the environment's deployment branch policy.
    # Lightsail IAM is coarse (Resource "*"), so this trust scope is the primary control.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/${var.github_repo}:environment:${var.github_environment}"]
    }
  }
}

resource "aws_iam_role" "github_image_push" {
  name               = "github-actions-lik-image-push"
  assume_role_policy = data.aws_iam_policy_document.github_trust.json
}

data "aws_iam_policy_document" "image_push" {
  statement {
    effect = "Allow"
    actions = [
      "lightsail:PushContainerImage",
      "lightsail:RegisterContainerImage",
      "lightsail:GetContainerImages",
      "lightsail:GetContainerServices",
    ]
    # Lightsail does not support resource-level ARNs for these actions.
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "image_push" {
  name   = "lightsail-image-push"
  role   = aws_iam_role.github_image_push.id
  policy = data.aws_iam_policy_document.image_push.json
}
