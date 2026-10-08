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

output "ask_url" {
  value = "${aws_api_gateway_stage.v1.invoke_url}/ask"
}

output "api_key" {
  value     = aws_api_gateway_api_key.tester.value
  sensitive = true
}

output "ask_function" {
  value = aws_lambda_function.ask.function_name
}

output "guardrail_id" {
  value = aws_bedrock_guardrail.ask.guardrail_id
}

output "guardrail_version" {
  value = aws_bedrock_guardrail_version.ask.version
}
