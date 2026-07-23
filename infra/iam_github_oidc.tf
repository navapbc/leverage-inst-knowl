# GitHub Actions -> AWS via OIDC (no long-lived keys). Two roles share the same trust
# (repo + `prod` environment): `github-actions-lik-image-push` is scoped to pushing
# container images; `github-actions-lik-apply` can run `terraform plan`/`apply` for the
# routine image-swap redeploy. `terraform apply` can still be run locally under
# AWS_PROFILE=lik for anything non-routine.

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
      "lightsail:CreateContainerServiceRegistryLogin", # registry login used by push-container-image
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

# --- Apply role: CI runs `terraform plan`/`apply` for the routine image swap -----------
# Least-privilege for the gated CI apply job (.github/workflows/deploy-images.yml): read
# everything Terraform refreshes, plus the single write the image-swap plan performs
# (CreateContainerServiceDeployment) and read/write on the S3 remote state + lockfile.
resource "aws_iam_role" "github_apply" {
  name               = "github-actions-lik-apply"
  assume_role_policy = data.aws_iam_policy_document.github_trust.json
}

data "aws_iam_policy_document" "apply" {
  # Remote state (S3 backend, native lockfile) — see backend.tf.
  statement {
    sid       = "TerraformState"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::ik-arch-tfstate-293033346213"]
  }
  statement {
    sid    = "TerraformStateObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    # State object + the `<key>.tflock` lock object live under this prefix.
    resources = ["arn:aws:s3:::ik-arch-tfstate-293033346213/ik-arch/prod/*"]
  }

  # SSM parameters Terraform reads (ssm.tf) + the DB password it authors (database.tf).
  # SecureString decryption uses the AWS-managed alias/aws/ssm key, whose default policy
  # already permits Decrypt to callers in this account with ssm:GetParameter — so no
  # explicit kms statement is included; add one only if a plan run fails with AccessDenied.
  statement {
    sid    = "SsmRead"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]
    resources = ["arn:aws:ssm:${var.aws_region}:293033346213:parameter/ik-arch/prod/*"]
  }

  # The aws_ssm_parameter managed resource (database.tf) reads parameter metadata via
  # ssm:DescribeParameters during plan/refresh. That action does not support resource-level
  # ARNs, so it must be granted on "*" in its own statement.
  statement {
    sid       = "SsmDescribe"
    effect    = "Allow"
    actions   = ["ssm:DescribeParameters"]
    resources = ["*"]
  }

  # Lightsail refresh (containers + database) plus the one write the image-swap performs.
  # Lightsail does not support resource-level ARNs, so Resource must be "*".
  statement {
    sid    = "LightsailReadAndDeploy"
    effect = "Allow"
    actions = [
      "lightsail:GetContainerServices",
      "lightsail:GetContainerServiceDeployments",
      "lightsail:GetContainerImages",
      "lightsail:GetRelationalDatabase",
      "lightsail:GetRelationalDatabases",
      "lightsail:CreateContainerServiceDeployment",
    ]
    resources = ["*"]
  }

  # Read-only refresh of the OIDC resources this config manages.
  statement {
    sid    = "IamReadForRefresh"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:GetOpenIDConnectProvider",
    ]
    resources = [
      aws_iam_role.github_image_push.arn,
      aws_iam_role.github_apply.arn,
      aws_iam_openid_connect_provider.github.arn,
    ]
  }
}

resource "aws_iam_role_policy" "apply" {
  name   = "terraform-apply"
  role   = aws_iam_role.github_apply.id
  policy = data.aws_iam_policy_document.apply.json
}
