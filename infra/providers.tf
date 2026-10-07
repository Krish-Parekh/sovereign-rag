provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = local.name
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name       = "sovereign-rag"
  account_id = data.aws_caller_identity.current.account_id
}
