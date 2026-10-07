resource "aws_cognito_user_pool" "users" {
  name                     = local.name
  user_pool_tier           = "ESSENTIALS"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = var.mfa_configuration
  deletion_protection      = "INACTIVE"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 1
  }

  dynamic "software_token_mfa_configuration" {
    for_each = var.mfa_configuration == "ON" ? [true] : []

    content {
      enabled = true
    }
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  username_configuration {
    case_sensitive = false
  }
}

resource "aws_cognito_user_pool_domain" "login" {
  domain                = "${local.name}-${local.account_id}"
  user_pool_id          = aws_cognito_user_pool.users.id
  managed_login_version = 2
}

resource "aws_cognito_resource_server" "api" {
  identifier   = local.name
  name         = local.name
  user_pool_id = aws_cognito_user_pool.users.id

  scope {
    scope_name        = "ask"
    scope_description = "Ask the support assistant"
  }
}

resource "aws_cognito_user_pool_client" "cli" {
  name                                 = "${local.name}-cli"
  user_pool_id                         = aws_cognito_user_pool.users.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "${aws_cognito_resource_server.api.identifier}/ask"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["http://localhost:8765/callback"]
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH"]
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 1
  enable_token_revocation              = true
  prevent_user_existence_errors        = "ENABLED"

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

resource "aws_cognito_managed_login_branding" "cli" {
  user_pool_id                = aws_cognito_user_pool.users.id
  client_id                   = aws_cognito_user_pool_client.cli.id
  use_cognito_provided_values = true
}
