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

output "docs_bucket" {
  value = aws_s3_bucket.docs.bucket
}

output "knowledge_base_id" {
  value = aws_bedrockagent_knowledge_base.help_centre.id
}

output "data_source_id" {
  value = aws_bedrockagent_data_source.corpus.data_source_id
}

output "chat_table" {
  value = aws_dynamodb_table.chat.name
}
