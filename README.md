# Sovereign RAG

Sovereign RAG is a customer-support assistant. It answers questions from Wix help-centre articles and cites its sources. All parts run in AWS Sydney (`ap-southeast-2`). Terraform creates and destroys the stack. The stack costs nothing when it is idle.

<img alt="AWS architecture in ap-southeast-2. Retrieval flow. 1. The user sends a question to API Gateway with a Cognito token and an API key. 2. API Gateway checks the token with Cognito. 3. API Gateway starts the ask Lambda. 4. The input guardrail masks personal data and blocks harmful questions. 5. The Lambda reads and writes masked chat history in DynamoDB. 6. The Knowledge Base retrieves chunks from S3 Vectors with a role filter. 7. Qwen3 32B writes the answer, and the output guardrail checks it. 8. API Gateway returns the answer to the user as JSON. CloudWatch Logs receives one line of metadata for each request. Ingestion flow. 9. prepare_corpus.py uploads WixQA markdown and metadata to the S3 docs bucket. 10. An ingestion job reads the corpus/ folder. 11. Titan V2 embeds the chunks into S3 Vectors." src="docs/architecture/architecture.png">

## How it works

- **Sign-in:** Each request needs a Cognito token and an API key. Users in the `staff` group also see known issues and feature requests. All other users see help articles only.
- **Guardrail:** The guardrail masks personal data, for example names, emails and phone numbers. It masks the question before the app stores or sends it, and it masks the answer. It also blocks harmful questions and prompt attacks.
- **Answer:** The Knowledge Base finds the 5 best chunks in S3 Vectors. Qwen3 32B writes an answer that cites these chunks. The Lambda function returns the full answer as JSON.
- **History:** DynamoDB keeps the masked chat turns for 30 days.
- **Corpus:** `prepare_corpus.py` uploads 563 WixQA documents and starts an ingestion job. Titan V2 embeds the documents.

## Trade-offs

- The answer comes back in one piece after about 1 to 2 seconds. It does not stream word by word, because the guardrail must check the full answer first.
- Masking also hides business addresses in answers. For example, `support@wix.com` shows as `{EMAIL}`.
- The stack has no tracing, metrics or alerts. We destroy the stack after each test.
