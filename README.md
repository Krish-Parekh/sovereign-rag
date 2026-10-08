# Sovereign RAG

Sovereign RAG is a customer-support assistant. It answers questions from Wix help-centre articles and cites its sources. All parts run in AWS Sydney (`ap-southeast-2`). Terraform creates and destroys the stack. The stack costs nothing when it is idle.

<img alt="AWS architecture in ap-southeast-2. Retrieval flow. 1. The user sends a question to API Gateway with a Cognito token and an API key. 2. API Gateway checks the token with Cognito. 3. API Gateway starts the ask Lambda. 4. The input guardrail masks personal data and blocks harmful questions. 5. The Lambda reads and writes masked chat history in DynamoDB. 6. The Knowledge Base retrieves chunks from S3 Vectors with a role filter. 7. Qwen3 32B writes the answer, and the output guardrail checks it. 8. API Gateway returns the answer to the user as JSON. CloudWatch Logs receives one line of metadata for each request. Ingestion flow. 9. prepare_corpus.py uploads WixQA markdown and metadata to the S3 docs bucket. 10. An ingestion job reads the corpus/ folder. 11. Titan V2 embeds the chunks into S3 Vectors." src="docs/architecture/architecture.png">

## How it works

- **Sign-in:** Each request needs a Cognito token and an API key. Users in the `staff` group also see known issues and feature requests. All other users see help articles only.
- **Guardrail:** The guardrail masks personal data, for example names, emails and phone numbers. It masks the question before the app stores or sends it, and it masks the answer. It also blocks harmful questions and prompt attacks.
- **Answer:** The Knowledge Base finds the 5 best chunks in S3 Vectors. Qwen3 32B writes an answer that cites these chunks. The Lambda function returns the full answer as JSON.
- **History:** DynamoDB keeps the masked chat turns for 30 days.
- **Corpus:** `prepare_corpus.py` uploads 563 WixQA documents and starts an ingestion job. Titan V2 embeds the documents.

## Try it

`scripts/tryout.py` is the fastest way to get a feel for the project. It creates a customer user and a staff user, signs you in through the browser, sends questions to the real API and runs the security checks. You do not need to copy tokens or write `curl` commands.

You need AWS credentials for `ap-southeast-2`, `uv`, Terraform, and an S3 bucket for the Terraform state. Copy `infra/backend.hcl.example` to `infra/backend.hcl` and `infra/terraform.tfvars.example` to `infra/terraform.tfvars`, then fill them in.

1. Deploy the stack and load the corpus:

   ```bash
   ./scripts/build.sh
   terraform -chdir=infra init -backend-config=backend.hcl
   terraform -chdir=infra apply
   uv run python scripts/prepare_corpus.py \
     --bucket "$(terraform -chdir=infra output -raw docs_bucket)" \
     --knowledge-base-id "$(terraform -chdir=infra output -raw knowledge_base_id)" \
     --data-source-id "$(terraform -chdir=infra output -raw data_source_id)"
   ```

2. Run all checks. A browser tab opens for each user, with the email already filled in. The terminal shows the password to type.

   ```bash
   uv run python scripts/tryout.py check
   ```

3. Ask your own questions:

   ```bash
   uv run python scripts/tryout.py ask "What are the steps to create an online store?"
   uv run python scripts/tryout.py ask "How do I add staff members in Wix Bookings?"
   uv run python scripts/tryout.py ask "Form fields are shown in multiple languages" --user staff
   uv run python scripts/tryout.py ask "and how long does that take?" --conversation-id <id>
   uv run python scripts/tryout.py users
   ```

   `--user staff` asks as a staff user, who also sees known issues. `--conversation-id` continues a conversation. `users` resets both passwords.

4. Destroy the stack when you finish:

   ```bash
   terraform -chdir=infra destroy
   ```

The corpus is a sample of 563 WixQA documents. If no document covers a question, the assistant says so and does not guess.
