output "user_pool_id" {
  value = aws_cognito_user_pool.users.id
}

output "client_id" {
  value = aws_cognito_user_pool_client.cli.id
}

output "login_domain" {
  value = "https://${aws_cognito_user_pool_domain.login.domain}.auth.${var.region}.amazoncognito.com"
}

output "issuer" {
  value = "https://${aws_cognito_user_pool.users.endpoint}"
}
