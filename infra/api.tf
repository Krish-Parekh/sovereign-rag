locals {
  web_adapter_layer = "arn:aws:lambda:${var.region}:753240598075:layer:LambdaAdapterLayerArm64:30"
  qwen_arn          = "arn:aws:bedrock:${var.region}::foundation-model/qwen.qwen3-32b-v1:0"
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
    sid       = "XrayNoResourceLevel"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:PutSpans"]
    resources = ["*"]

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
  handler          = "run.sh"
  filename         = data.archive_file.ask.output_path
  source_code_hash = data.archive_file.ask.output_base64sha256
  memory_size      = 1024
  timeout          = 300
  layers           = [local.web_adapter_layer]

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      AWS_LAMBDA_EXEC_WRAPPER                            = "/opt/bootstrap"
      AWS_LWA_INVOKE_MODE                                = "response_stream"
      AWS_LWA_PORT                                       = "8080"
      PYTHONUNBUFFERED                                   = "1"
      KNOWLEDGE_BASE_ID                                  = aws_bedrockagent_knowledge_base.help_centre.id
      CHAT_TABLE                                         = aws_dynamodb_table.chat.name
      CHAT_MODEL                                         = var.chat_model
      OTEL_PYTHON_DISTRO                                 = "aws_distro"
      OTEL_PYTHON_CONFIGURATOR                           = "aws_configurator"
      OTEL_EXPORTER_OTLP_PROTOCOL                        = "http/protobuf"
      OTEL_EXPORTER_OTLP_TRACES_ENDPOINT                 = "https://xray.${var.region}.amazonaws.com/v1/traces"
      OTEL_TRACES_EXPORTER                               = "otlp"
      OTEL_METRICS_EXPORTER                              = "none"
      OTEL_LOGS_EXPORTER                                 = "none"
      OTEL_SERVICE_NAME                                  = "${local.name}-ask"
      OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT = "false"
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
  uri                     = aws_lambda_function.ask.response_streaming_invoke_arn
  response_transfer_mode  = "STREAM"
  timeout_milliseconds    = 300000
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
  rest_api_id          = aws_api_gateway_rest_api.api.id
  deployment_id        = aws_api_gateway_deployment.api.id
  stage_name           = "v1"
  xray_tracing_enabled = true
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
    rate_limit  = 1
    burst_limit = 2
  }

  quota_settings {
    limit  = 500
    period = "DAY"
  }
}

resource "aws_api_gateway_usage_plan_key" "tester" {
  key_id        = aws_api_gateway_api_key.tester.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.tester.id
}
