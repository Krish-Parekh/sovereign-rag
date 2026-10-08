locals {
  qwen_arn = "arn:aws:bedrock:${var.region}::foundation-model/qwen.qwen3-32b-v1:0"
}

resource "aws_cloudwatch_log_group" "ask" {
  name              = "/aws/lambda/${local.name}-ask"
  retention_in_days = 14
}

data "archive_file" "ask" {
  type             = "zip"
  source_dir       = "${path.module}/../build/ask"
  output_path      = "${path.module}/../build/ask.zip"
  output_file_mode = "0755"
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ask" {
  name               = "${local.name}-ask"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "ask" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ask.arn}:*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid       = "ChatHistory"
    actions   = ["dynamodb:Query", "dynamodb:PutItem"]
    resources = [aws_dynamodb_table.chat.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid       = "Retrieve"
    actions   = ["bedrock:Retrieve"]
    resources = [aws_bedrockagent_knowledge_base.help_centre.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid       = "Generate"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [local.qwen_arn]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid       = "Guardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.ask.guardrail_arn]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }
}

resource "aws_iam_role_policy" "ask" {
  role   = aws_iam_role.ask.id
  policy = data.aws_iam_policy_document.ask.json
}

resource "aws_lambda_function" "ask" {
  function_name    = "${local.name}-ask"
  role             = aws_iam_role.ask.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "main.handler"
  filename         = data.archive_file.ask.output_path
  source_code_hash = data.archive_file.ask.output_base64sha256
  memory_size      = 1024
  timeout          = 60

  environment {
    variables = {
      KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.help_centre.id
      CHAT_TABLE        = aws_dynamodb_table.chat.name
      CHAT_MODEL        = var.chat_model
      GUARDRAIL_ID      = aws_bedrock_guardrail.ask.guardrail_id
      GUARDRAIL_VERSION = aws_bedrock_guardrail_version.ask.version
    }
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.ask.name
  }

  depends_on = [aws_iam_role_policy.ask]
}

resource "aws_api_gateway_rest_api" "api" {
  name = local.name

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "ask" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "ask"
}

resource "aws_api_gateway_authorizer" "cognito" {
  name            = "${local.name}-cognito"
  rest_api_id     = aws_api_gateway_rest_api.api.id
  type            = "COGNITO_USER_POOLS"
  provider_arns   = [aws_cognito_user_pool.users.arn]
  identity_source = "method.request.header.Authorization"
}

resource "aws_api_gateway_method" "ask" {
  rest_api_id          = aws_api_gateway_rest_api.api.id
  resource_id          = aws_api_gateway_resource.ask.id
  http_method          = "POST"
  authorization        = "COGNITO_USER_POOLS"
  authorizer_id        = aws_api_gateway_authorizer.cognito.id
  authorization_scopes = ["${aws_cognito_resource_server.api.identifier}/ask"]
  api_key_required     = true
}

resource "aws_api_gateway_integration" "ask" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.ask.id
  http_method             = aws_api_gateway_method.ask.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.ask.invoke_arn
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ask.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/POST/ask"
}

resource "aws_api_gateway_deployment" "api" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.ask,
      aws_api_gateway_authorizer.cognito,
      aws_api_gateway_method.ask,
      aws_api_gateway_integration.ask,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "v1" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  deployment_id = aws_api_gateway_deployment.api.id
  stage_name    = "v1"
}

resource "aws_api_gateway_api_key" "tester" {
  name = "${local.name}-tester"
}

resource "aws_api_gateway_usage_plan" "tester" {
  name = "${local.name}-tester"

  api_stages {
    api_id = aws_api_gateway_rest_api.api.id
    stage  = aws_api_gateway_stage.v1.stage_name
  }

  throttle_settings {
    rate_limit  = var.api_rate_limit
    burst_limit = var.api_burst_limit
  }

  dynamic "quota_settings" {
    for_each = var.api_daily_quota > 0 ? [var.api_daily_quota] : []

    content {
      limit  = quota_settings.value
      period = "DAY"
    }
  }
}

resource "aws_api_gateway_usage_plan_key" "tester" {
  key_id        = aws_api_gateway_api_key.tester.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.tester.id
}
