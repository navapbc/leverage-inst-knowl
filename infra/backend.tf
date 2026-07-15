# Remote state on S3 with native locking (Terraform >= 1.10; no DynamoDB table needed).
# The bucket must exist with versioning enabled BEFORE `terraform init` — it is created
# once out-of-band (see docs/deploy-runbook.md "Bootstrap the state bucket"). Backend
# blocks cannot use variables, so the bucket name is literal here.
terraform {
  required_version = ">= 1.10"

  backend "s3" {
    bucket       = "ik-arch-tfstate-293033346213"
    key          = "ik-arch/prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
