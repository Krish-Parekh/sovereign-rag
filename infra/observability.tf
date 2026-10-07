resource "aws_cloudwatch_log_group" "ask" {
  name              = "/aws/lambda/${local.name}-ask"
  retention_in_days = 14
}
