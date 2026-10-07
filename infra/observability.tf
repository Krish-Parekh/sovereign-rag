resource "aws_cloudwatch_log_group" "ask" {
  name              = "/aws/lambda/${local.name}-ask"
  retention_in_days = 14
}

locals {
  api_dimensions = ["ApiName", aws_api_gateway_rest_api.api.name, "Stage", aws_api_gateway_stage.v1.stage_name]
  step_metrics   = ["RetrieveMs", "TTFTMs", "GenerateMs", "TotalMs"]

  alarms = {
    api-5xx = {
      namespace  = "AWS/ApiGateway"
      metric     = "5XXError"
      threshold  = 1
      dimensions = { ApiName = aws_api_gateway_rest_api.api.name, Stage = aws_api_gateway_stage.v1.stage_name }
    }
    api-4xx = {
      namespace  = "AWS/ApiGateway"
      metric     = "4XXError"
      threshold  = 20
      dimensions = { ApiName = aws_api_gateway_rest_api.api.name, Stage = aws_api_gateway_stage.v1.stage_name }
    }
    ask-errors = {
      namespace  = "SovereignRag"
      metric     = "AskErrors"
      threshold  = 1
      dimensions = {}
    }
  }
}

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "alarms" {
  for_each = local.alarms

  alarm_name          = "${local.name}-${each.key}"
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Step latency p50 (ms)"
          region  = var.region
          stat    = "p50"
          period  = 300
          view    = "timeSeries"
          metrics = [for m in local.step_metrics : ["SovereignRag", m]]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Step latency p90 (ms)"
          region  = var.region
          stat    = "p90"
          period  = 300
          view    = "timeSeries"
          metrics = [for m in local.step_metrics : ["SovereignRag", m]]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "Answers"
          region = var.region
          period = 300
          view   = "timeSeries"
          metrics = [
            ["SovereignRag", "TokensOut", { stat = "Average" }],
            ["SovereignRag", "TopScore", { stat = "Average", yAxis = "right" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "API"
          region = var.region
          stat   = "Sum"
          period = 300
          view   = "timeSeries"
          metrics = [
            concat(["AWS/ApiGateway", "Count"], local.api_dimensions),
            concat(["AWS/ApiGateway", "4XXError"], local.api_dimensions),
            concat(["AWS/ApiGateway", "5XXError"], local.api_dimensions),
            ["SovereignRag", "AskErrors"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "Lambda"
          region = var.region
          stat   = "Sum"
          period = 300
          view   = "timeSeries"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.ask.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.ask.function_name],
          ]
        }
      },
    ]
  })
}
