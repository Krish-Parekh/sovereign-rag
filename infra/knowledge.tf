locals {
  titan_arn = "arn:aws:bedrock:${var.region}::foundation-model/amazon.titan-embed-text-v2:0"
}

data "aws_iam_policy_document" "kb_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock:${var.region}:${local.account_id}:knowledge-base/*"]
    }
  }
}

resource "aws_iam_role" "kb" {
  name               = "${local.name}-kb"
  assume_role_policy = data.aws_iam_policy_document.kb_assume.json
}

data "aws_iam_policy_document" "kb" {
  statement {
    sid       = "ListCorpus"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.docs.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["corpus/*"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid       = "ReadCorpus"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.docs.arn}/corpus/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid       = "Embed"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.titan_arn]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid = "WriteVectors"
    actions = [
      "s3vectors:PutVectors",
      "s3vectors:GetVectors",
      "s3vectors:DeleteVectors",
      "s3vectors:QueryVectors",
      "s3vectors:GetIndex",
    ]
    resources = [aws_s3vectors_index.help_centre.index_arn]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }
}

resource "aws_iam_role_policy" "kb" {
  role   = aws_iam_role.kb.id
  policy = data.aws_iam_policy_document.kb.json
}

resource "aws_bedrockagent_knowledge_base" "help_centre" {
  name     = "${local.name}-kb"
  role_arn = aws_iam_role.kb.arn

  knowledge_base_configuration {
    type = "VECTOR"

    vector_knowledge_base_configuration {
      embedding_model_arn = local.titan_arn

      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions          = 1024
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }

  storage_configuration {
    type = "S3_VECTORS"

    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.help_centre.index_arn
    }
  }

  depends_on = [aws_iam_role_policy.kb]
}

resource "aws_bedrockagent_data_source" "corpus" {
  knowledge_base_id    = aws_bedrockagent_knowledge_base.help_centre.id
  name                 = "${local.name}-corpus"
  data_deletion_policy = "DELETE"

  data_source_configuration {
    type = "S3"

    s3_configuration {
      bucket_arn         = aws_s3_bucket.docs.arn
      inclusion_prefixes = ["corpus/"]
    }
  }

  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"

      fixed_size_chunking_configuration {
        max_tokens         = 400
        overlap_percentage = 15
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "kb" {
  name              = "/aws/vendedlogs/bedrock/${local.name}-kb"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_delivery_source" "kb" {
  name         = "${local.name}-kb"
  log_type     = "APPLICATION_LOGS"
  resource_arn = aws_bedrockagent_knowledge_base.help_centre.arn
}

resource "aws_cloudwatch_log_delivery_destination" "kb" {
  name = "${local.name}-kb"

  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.kb.arn
  }
}

resource "aws_cloudwatch_log_delivery" "kb" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.kb.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.kb.arn
}
